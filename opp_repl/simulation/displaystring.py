# This module provides plain textual eventlog comparison.

import logging
import os
import re

from opp_repl.common import *
from opp_repl.common.eventlog import *
from opp_repl.simulation.eventlog import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)


class EventlogDivergencePosition:
    def __init__(self, line_number, line_1, line_2, simulation_event_1, simulation_event_2):
        self.line_number = line_number
        self.line_1 = line_1
        self.line_2 = line_2
        self.simulation_event_1 = simulation_event_1
        self.simulation_event_2 = simulation_event_2

    def __repr__(self):
        return f"Eventlog divergence point:\n{self.get_description()}"

    def get_description(self):
        parts = []
        if self.simulation_event_1:
            parts.append(f"  Side 1: {self.simulation_event_1.get_description()}")
        parts.append(f"    {self.line_1!r}")
        if self.simulation_event_2:
            parts.append(f"  Side 2: {self.simulation_event_2.get_description()}")
        parts.append(f"    {self.line_2!r}")
        return "\n".join(parts)


class EventlogSimulationEvent(SimulationEvent):
    def __init__(self, simulation_result, event_number):
        self.simulation_result = simulation_result
        simulation_config = simulation_result.task.simulation_config
        simulation_project = simulation_config.simulation_project
        eventlog_file_path = simulation_project.get_full_path(
            os.path.join(simulation_config.working_directory, simulation_result.eventlog_file_path))
        eventlog = create_eventlog(eventlog_file_path)
        super().__init__(event_number, eventlog)


def read_eventlog_lines(simulation_result, filter=None, exclude_filter=None, full_match=False):
    """Read eventlog lines and return (event_numbers, lines) lists.

    Each line is associated with the event number of the most recent
    preceding E (event) line.  Header lines before the first event are
    skipped (they contain run-specific metadata like run IDs and timestamps).

    Lines can be filtered using ``filter`` (include regex) and
    ``exclude_filter`` (exclude regex), analogous to stdout filtering.
    """
    from opp_repl.common.util import matches_filter as _matches_filter
    simulation_config = simulation_result.task.simulation_config
    simulation_project = simulation_config.simulation_project
    file_path = simulation_project.get_full_path(
        simulation_config.working_directory + "/" + simulation_result.eventlog_file_path)
    event_numbers = []
    lines = []
    event_number = -1
    in_events = False
    event_pattern = re.compile(r'^E # (\d+) ')
    with open(file_path) as f:
        for line in f:
            line = line.rstrip('\n')
            m = event_pattern.match(line)
            if m:
                event_number = int(m.group(1))
                in_events = True
            if not in_events:
                continue
            if _matches_filter(line, filter, exclude_filter, full_match):
                event_numbers.append(event_number)
                lines.append(line)
    return event_numbers, lines


def find_eventlog_divergence_position(event_numbers_1, lines_1, event_numbers_2, lines_2,
                                      simulation_result_1, simulation_result_2):
    """Compare eventlog lines sequentially, return the first divergence point or None."""
    min_size = min(len(lines_1), len(lines_2))
    for i in range(min_size):
        if lines_1[i] != lines_2[i]:
            sim_event_1 = EventlogSimulationEvent(simulation_result_1, event_numbers_1[i])
            sim_event_2 = EventlogSimulationEvent(simulation_result_2, event_numbers_2[i])
            return EventlogDivergencePosition(i, lines_1[i], lines_2[i], sim_event_1, sim_event_2)
    if len(lines_1) != len(lines_2):
        longer_idx = min_size
        line_1 = lines_1[longer_idx] if longer_idx < len(lines_1) else "<end of file>"
        line_2 = lines_2[longer_idx] if longer_idx < len(lines_2) else "<end of file>"
        en_1 = event_numbers_1[longer_idx] if longer_idx < len(event_numbers_1) else -1
        en_2 = event_numbers_2[longer_idx] if longer_idx < len(event_numbers_2) else -1
        sim_event_1 = EventlogSimulationEvent(simulation_result_1, en_1) if en_1 >= 0 else None
        sim_event_2 = EventlogSimulationEvent(simulation_result_2, en_2) if en_2 >= 0 else None
        return EventlogDivergencePosition(longer_idx, line_1, line_2, sim_event_1, sim_event_2)
    return None
