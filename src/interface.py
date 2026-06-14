"""The measurement layer: a platform-agnostic interface plus the WidowX adapter.

The protocol on top (the gate, the maintenance layer) never touches a robot SDK;
it asks only for the primitives below, so adding a platform is one adapter. The
vitals check adds NO sensors: every primitive reads a register the servo already
reports. For the WidowX those are real DYNAMIXEL control-table registers,
documented with their addresses below. In this repo the adapter reads a simulated
bus so the demo runs with no hardware; a real dynamixel-sdk bus is a one-class
swap. Where the rest of PI's fleet exposes the same data is in
OTHER_PLATFORM_SOURCES at the bottom of this file.
"""

from abc import ABC, abstractmethod

# Servo temperature limits come from config.json (single source of truth).
from config import MODEL_TEMPERATURE_LIMIT_C, SERVO_TEMPERATURE_LIMIT_C


class HardwareInterface(ABC):
    """The primitive reads the vitals protocol needs from any platform.

    Temperatures are in degrees Celsius, currents in amperes, voltage in volts.
    Keys are joint or servo names, stable across reads for a given platform.
    """

    platform = "abstract"

    @abstractmethod
    def read_joint_temperatures(self):
        """Return {joint_name: temperature_celsius} for every actuated joint."""

    @abstractmethod
    def read_joint_currents_at_reference_motion(self):
        """Return {joint_name: current_amperes} while the arm executes the fixed
        reference motion. The caller is responsible for commanding that motion;
        this method only reads. Constant commanded motion is what makes a rising
        current attributable to wear rather than to a heavier load."""

    def read_input_voltage(self):
        """Return the bus input voltage in volts, or None if not exposed.

        Optional secondary read. A sagging supply, like a hot motor, leaves the
        actuator unable to source commanded torque, so it shares the thermal
        theme. Default None so platforms that do not expose it need not override.
        """
        return None


# DYNAMIXEL X-series Protocol 2.0 control-table addresses (real, read-only).
# Source: Robotis DYNAMIXEL e-Manual control table for XM430-W350 / XL430-W250.
# These are the registers the servo already publishes; we add nothing.
# Verify against the e-Manual at deployment (see README citation note).
ADDR_PRESENT_CURRENT = 126        # 2 bytes, signed
ADDR_PRESENT_POSITION = 132       # 4 bytes, unit 1 pulse
ADDR_PRESENT_INPUT_VOLTAGE = 144  # 2 bytes, unit 0.1 V
ADDR_PRESENT_TEMPERATURE = 146    # 1 byte, unit 1 degree C

# Present Current unit is model-specific: 2.69 mA per count on the XM430-W350.
# The XL430-W250 uses a different unit, so a production adapter maps the unit per
# model. The effort channel trends an XM430 joint (shoulder_1), so the XM430 unit
# applies here; the cooler XL430 joints are not used for effort.
UNIT_CURRENT_A = 0.00269          # amperes per Present Current count, XM430-W350
UNIT_VOLTAGE_V = 0.1              # volts per Present Input Voltage count
UNIT_TEMPERATURE_C = 1.0          # degrees C per Present Temperature count

# Operating temperature ceilings come from config.json (imported above): the
# XM430-W350 is rated -5 to +80 C, the XL430-W250 is rated -5 to +72 C. The 80 C
# XM430 ceiling is the one hard, sourced number the gate hangs on, because the
# high-torque XM430 joints (shoulder, elbow) always run hottest and therefore
# always bind the gate. The cooler XL430 wrist and gripper joints carry the lower
# 72 C limit but never approach it, so the gate is correctly bound by an XM430
# joint. MODEL_TEMPERATURE_LIMIT_C and SERVO_TEMPERATURE_LIMIT_C are imported.


class RegisterBus(ABC):
    """The low-level byte read the adapter delegates to.

    A real bus wraps dynamixel-sdk (GroupSyncRead / read1ByteTxRx). The repo
    ships a simulated bus. The adapter is identical either way.
    """

    @abstractmethod
    def read_register(self, dxl_id, address, length):
        """Return the raw integer in the register at `address` for servo `dxl_id`."""


class WidowXAdapter(HardwareInterface):
    """Interbotix / Trossen WidowX-250 6DOF, the arm PI's OpenPI and ALOHA /
    Trossen stacks are built on, and the arm class the AutoEval paper documents
    overheating after about 8 hours.

    Servo layout matches the WidowX-250 6DOF: seven XM430-W350 on the main
    joints (some doubled for torque) and two XL430-W250 on the lighter wrist and
    gripper joints, nine servos in all. They present as seven logical joints
    (shoulder and elbow each aggregate their two servos to the hotter one), and
    each joint is scored against its own datasheet limit, not a single arm number.
    """

    platform = "widowx-250-6dof"

    # Real servo layout (nine servos): seven XM430-W350 plus two XL430-W250.
    # (servo_name, dxl_id, model). Each servo reports its own temperature.
    SERVOS = (
        ("waist", 1, "XM430-W350"),
        ("shoulder_1", 2, "XM430-W350"),
        ("shoulder_2", 3, "XM430-W350"),
        ("elbow_1", 4, "XM430-W350"),
        ("elbow_2", 5, "XM430-W350"),
        ("forearm_roll", 6, "XM430-W350"),
        ("wrist_angle", 7, "XM430-W350"),
        ("wrist_rotate", 8, "XL430-W250"),
        ("gripper", 9, "XL430-W250"),
    )

    # The seven logical joints the gate scores. Shoulder and elbow each aggregate
    # their two servos to the hotter one (the servo at risk), so nine servos
    # present as seven joints. (joint, model, (servo_names,))
    JOINTS = (
        ("waist", "XM430-W350", ("waist",)),
        ("shoulder", "XM430-W350", ("shoulder_1", "shoulder_2")),
        ("elbow", "XM430-W350", ("elbow_1", "elbow_2")),
        ("forearm_roll", "XM430-W350", ("forearm_roll",)),
        ("wrist_angle", "XM430-W350", ("wrist_angle",)),
        ("wrist_rotate", "XL430-W250", ("wrist_rotate",)),
        ("gripper", "XL430-W250", ("gripper",)),
    )

    def __init__(self, bus):
        self.bus = bus
        self._id = {name: dxl_id for name, dxl_id, _ in self.SERVOS}

    def _servo_temp(self, servo_name):
        raw = self.bus.read_register(self._id[servo_name], ADDR_PRESENT_TEMPERATURE, 1)
        return raw * UNIT_TEMPERATURE_C

    def _servo_current(self, servo_name):
        raw = self.bus.read_register(self._id[servo_name], ADDR_PRESENT_CURRENT, 2)
        return raw * UNIT_CURRENT_A

    def read_joint_temperatures(self):
        # one temperature per joint: the hotter servo of a dual-servo joint
        return {joint: max(self._servo_temp(s) for s in servos)
                for joint, _model, servos in self.JOINTS}

    def read_joint_currents_at_reference_motion(self):
        return {joint: max(self._servo_current(s) for s in servos)
                for joint, _model, servos in self.JOINTS}

    def joint_limits(self):
        """The datasheet temperature limit for each joint, for the gate to score
        against (80 C XM430, 72 C XL430)."""
        return {joint: MODEL_TEMPERATURE_LIMIT_C[model] for joint, model, _ in self.JOINTS}

    def read_input_voltage(self):
        # All servos share the same supply; read one representative servo.
        raw = self.bus.read_register(self.SERVOS[0][1], ADDR_PRESENT_INPUT_VOLTAGE, 2)
        return raw * UNIT_VOLTAGE_V


class SimulatedDynamixelBus(RegisterBus):
    """A RegisterBus backed by synthetic physical readings, for the demo.

    It converts physical values (degrees C, amperes, volts) back into the raw
    register counts a real servo would report, so the adapter performs the same
    unit conversion it would against hardware. This is the only stand-in for the
    serial bus; everything above it is the real code path.
    """

    def __init__(self, temperatures_c, currents_a=None, voltage_v=12.0):
        # temperatures_c, currents_a: {joint_name: value}. We index by dxl_id via
        # the adapter's servo map so the bus speaks in IDs like the real one.
        self._id_to_name = {dxl_id: name for name, dxl_id, _ in WidowXAdapter.SERVOS}
        self._temperatures_c = temperatures_c
        self._currents_a = currents_a or {}
        self._voltage_v = voltage_v

    def read_register(self, dxl_id, address, length):
        name = self._id_to_name[dxl_id]
        if address == ADDR_PRESENT_TEMPERATURE:
            return round(self._temperatures_c[name] / UNIT_TEMPERATURE_C)
        if address == ADDR_PRESENT_CURRENT:
            return round(self._currents_a.get(name, 0.0) / UNIT_CURRENT_A)
        if address == ADDR_PRESENT_INPUT_VOLTAGE:
            return round(self._voltage_v / UNIT_VOLTAGE_V)
        raise ValueError(f"simulated bus has no register at address {address}")


# The rest of PI's fleet plugs in by writing one adapter against the real data
# source named here. Documented, not faked: each entry names the exact register
# or field a real adapter would read, no added sensors, just like the WidowX path.
# Faking these SDKs would produce shallow, probably-wrong code a platform engineer
# would see through, so this stays a provenance table rather than empty classes.
OTHER_PLATFORM_SOURCES = {
    "ur5e": {  # Universal Robots UR5e, used in PI's pi0.7 laundry result
        "temperature": "RTDE output 'joint_temperatures' (per joint, deg C)",
        "current": "RTDE output 'actual_current' (per joint, A)",
    },
    "franka": {  # Franka Panda / Research 3, one of pi0's platforms
        "temperature": "Franka diagnostics channel (not exposed in libfranka RobotState)",
        "current": "libfranka RobotState.tau_J (measured joint torques)",
    },
    "arx": {  # bimanual ARX, one of pi0's platforms
        "temperature": "ARX SDK motor-driver thermal feedback (where exposed)",
        "current": "ARX SDK per-joint motor current estimate",
    },
}
