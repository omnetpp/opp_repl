# Minimal pure-Python eventlog parser compatible with the OMNeT++ .elog format.
# Only implements the subset of the C++/Java EventLog API that is actually
# used by the opp_repl Python code (SimulationEvent and friends).

import logging
import re

_logger = logging.getLogger(__name__)


def _parse_tokens(line):
    """Parse a line of key-value tokens from an .elog file.

    Returns the entry tag (e.g. 'E', 'MC', 'BS') and a dict of token
    key→value pairs.  String values that were quoted in the file are
    unquoted automatically.
    """
    parts = line.split()
    if not parts:
        return None, {}
    tag = parts[0]
    tokens = {}
    i = 1
    while i < len(parts):
        key = parts[i]
        i += 1
        if i < len(parts):
            value = parts[i]
            if value.startswith('"'):
                # collect until closing quote
                while not value.endswith('"') and i + 1 < len(parts):
                    i += 1
                    value += " " + parts[i]
                value = value.strip('"')
            tokens[key] = value
            i += 1
    return tag, tokens


# ---------------------------------------------------------------------------
# Entry classes – thin data holders matching the C++ API used from Python
# ---------------------------------------------------------------------------

class ModuleDescriptionEntry:
    """Mirrors the subset of omnetpp::eventlog::ModuleDescriptionEntry
    that is used by SimulationEvent."""

    def __init__(self, module_id, module_class_name, ned_type_name,
                 parent_module_id, full_name, compound_module):
        self.moduleId = module_id
        self.moduleClassName = module_class_name
        self.nedTypeName = ned_type_name
        self.parentModuleId = parent_module_id
        self.fullName = full_name
        self.compoundModule = compound_module

    # public API (Java-style getters expected by SimulationEvent)
    def getModuleId(self):
        return self.moduleId

    def getFullName(self):
        return self.fullName

    def getNedTypeName(self):
        return self.nedTypeName

    def getParentModuleId(self):
        return self.parentModuleId


class BeginSendEntry:
    """Mirrors the subset of omnetpp::eventlog::BeginSendEntry
    that is used by SimulationEvent."""

    def __init__(self, tokens):
        self.messageId = int(tokens.get("id", -1))
        self.messageName = tokens.get("n", "")
        self.previousEventNumber = int(tokens.get("pe", -1))

    def getMessageName(self):
        return self.messageName


# ---------------------------------------------------------------------------
# EventLogEntryCache
# ---------------------------------------------------------------------------

class EventLogEntryCache:
    """Provides fast moduleId → ModuleDescriptionEntry lookup."""

    def __init__(self):
        self._module_map = {}  # moduleId -> ModuleDescriptionEntry

    def addModuleDescriptionEntry(self, entry):
        self._module_map[entry.moduleId] = entry

    def getModuleDescriptionEntry(self, module_id):
        return self._module_map.get(module_id)


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

class Event:
    """Minimal mirror of omnetpp::eventlog::Event."""

    def __init__(self, event_number, simulation_time, module_id,
                 cause_event_number, message_id, eventlog):
        self.eventNumber = event_number
        self.simulationTime = simulation_time
        self.moduleId = module_id
        self.causeEventNumber = cause_event_number
        self.messageId = message_id
        self._eventlog = eventlog
        self._entries = []         # all parsed EventLogEntry-like objects in this event
        self._begin_send_entries = []
        self._module_description_entry = None  # lazily resolved

    # -- public API used by SimulationEvent ----------------------------------

    def getEventNumber(self):
        return self.eventNumber

    def getSimulationTime(self):
        return self.simulationTime

    def getModuleId(self):
        return self.moduleId

    def getMessageId(self):
        return self.messageId

    def getCauseEventNumber(self):
        return self.causeEventNumber

    def getModuleDescriptionEntry(self):
        if self._module_description_entry is None:
            self._module_description_entry = (
                self._eventlog.getEventLogEntryCache()
                    .getModuleDescriptionEntry(self.moduleId))
        return self._module_description_entry

    def getCauseEvent(self):
        if self.causeEventNumber == -1:
            return None
        return self._eventlog.getEventForEventNumber(self.causeEventNumber)

    def getCauseBeginSendEntry(self):
        cause_event = self.getCauseEvent()
        if cause_event is None:
            return None
        for bs in cause_event._begin_send_entries:
            if bs.messageId == self.messageId:
                return bs
        return None


# ---------------------------------------------------------------------------
# EventLog  –  the top-level container
# ---------------------------------------------------------------------------

class EventLog:
    """Pure-Python parser for OMNeT++ .elog files.

    Only the features required by the opp_repl ``SimulationEvent`` class are
    implemented.
    """

    def __init__(self, file_path):
        self._file_path = file_path
        self._events = {}                # eventNumber -> Event
        self._entry_cache = EventLogEntryCache()
        self._parse(file_path)

    # -- public API ----------------------------------------------------------

    def getEventForEventNumber(self, event_number):
        return self._events.get(event_number)

    def getEventLogEntryCache(self):
        return self._entry_cache

    # -- parsing -------------------------------------------------------------

    def _parse(self, file_path):
        current_event = None
        with open(file_path, "r") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    current_event = None
                    continue
                tag, tokens = _parse_tokens(line)
                if tag is None:
                    continue

                if tag == "E":
                    event_number = int(tokens.get("#", -1))
                    simulation_time = tokens.get("t", "0")
                    module_id = int(tokens.get("m", -1))
                    cause_event_number = int(tokens.get("ce", -1))
                    message_id = int(tokens.get("msg", -1))
                    current_event = Event(
                        event_number, simulation_time, module_id,
                        cause_event_number, message_id, self)
                    self._events[event_number] = current_event

                elif tag == "MC" or tag == "MF":
                    entry = ModuleDescriptionEntry(
                        module_id=int(tokens.get("id", -1)),
                        module_class_name=tokens.get("c", ""),
                        ned_type_name=tokens.get("t", ""),
                        parent_module_id=int(tokens.get("pid", -1)),
                        full_name=tokens.get("n", ""),
                        compound_module=tokens.get("cm", "0") != "0",
                    )
                    self._entry_cache.addModuleDescriptionEntry(entry)

                elif tag == "BS":
                    bs = BeginSendEntry(tokens)
                    if current_event is not None:
                        current_event._begin_send_entries.append(bs)
                        current_event._entries.append(bs)


def create_eventlog(file_path):
    """Create an EventLog from the given .elog file path.

    Returns ``None`` when the file cannot be read.
    """
    try:
        return EventLog(file_path)
    except Exception:
        _logger.warning("Cannot load eventlog from %s", file_path)
        return None
