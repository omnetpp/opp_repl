import argparse
import csv
import glob
import logging
import re
import shlex

from opp_repl.test.fingerprint import *

from opp_repl.common import *
from opp_repl.simulation.project import *
from opp_repl.test.fingerprint.store import *
from opp_repl.test.fingerprint.task import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def update_correct_fingerprints_from_csv(csv_file, correct_fingerprints, filter=None, exclude_filter=None, full_match=False, timestamp=None):
    def commentRemover(csv_data):
        p = re.compile(" *#.*$")
        for line in csv_data:
            yield p.sub("",line.decode("utf-8"))
    ini_sim_time_limits = None
    def get_ini_sim_time_limit(working_directory, ini_file, config):
        # an empty CSV limit means the limit of the config in its ini file; the store
        # always names the limit, because the runner cannot run an entry without one
        nonlocal ini_sim_time_limits
        if ini_sim_time_limits is None:
            simulation_configs = correct_fingerprints.simulation_project.get_simulation_configs(simulation_config_filter=lambda simulation_config: True)
            ini_sim_time_limits = {(c.working_directory, c.ini_file, c.config): c.sim_time_limit for c in simulation_configs}
        return ini_sim_time_limits.get((working_directory, ini_file, config))
    entries = []
    f = open(csv_file, "rb")
    csvReader = csv.reader(commentRemover(f), delimiter=str(","), quotechar=str("'"), skipinitialspace=True)
    for fields in csvReader:
        if len(fields) == 0:
            pass        # empty line
        elif len(fields) == 6:
            if not matches_filter(str(fields), filter, exclude_filter, full_match):
                continue
            elif fields[4] in ["PASS", "FAIL", "ERROR"]:
                parser = argparse.ArgumentParser()
                parser.add_argument("-f", "--ini_file", default="omnetpp.ini")
                parser.add_argument("-c", "--config", default="General")
                parser.add_argument("-r", "--run", default="0")
                args = parser.parse_args(shlex.split(fields[1]))
                fingerprints = map(lambda text: Fingerprint.parse(text), fields[3].split(";"))
                working_directory = fields[0] if fields[0] != "." else "tests/fingerprint"
                if working_directory[0] == '/':
                    working_directory = working_directory[1:]
                if working_directory[-1] == '/':
                    working_directory = working_directory[:-1]
                _logger.info("Updating correct fingerprint: " + working_directory + " -f " + args.ini_file + " -c " + args.config + " -r " + args.run)
                # -r may be a run number OR an iteration-variable run filter,
                # e.g. "$datarate==10Mbps && ... && $repetition==0" (parameter
                # studies). Keep the filter verbatim so it can be passed to
                # opp_run -r; only plain integers become an int run_number.
                run_spec = args.run.strip()
                run_number = int(run_spec) if re.fullmatch(r"-?\d+", run_spec) else run_spec
                sim_time_limit = fields[2].strip() or get_ini_sim_time_limit(working_directory, args.ini_file, args.config)
                if sim_time_limit is None:
                    _logger.warn(csv_file + " Line " + str(csvReader.line_num) + ": no sim-time-limit in the row or in the ini file")
                for fingerprint in fingerprints:
                    try:
                        correct_fingerprints.update_fingerprint(fingerprint.fingerprint,
                                                                timestamp=timestamp,
                                                                working_directory=working_directory,
                                                                ini_file=args.ini_file,
                                                                config=args.config,
                                                                run_number=run_number,
                                                                sim_time_limit=sim_time_limit,
                                                                ingredients=fingerprint.ingredients,
                                                                test_result=fields[4])
                    except Exception as e:
                        _logger.warn("Failed to update correct fingerprint: " + str(e))
            else:
                raise Exception(csv_file + " Line " + str(csvReader.line_num) + ": the 5th item must contain one of 'PASS', 'FAIL', 'ERROR'" + ": " + '"' + '", "'.join(fields) + '"')
        else:
            raise Exception(csv_file + " Line " + str(csvReader.line_num) + " must contain 6 items, but contains " + str(len(fields)) + ": " + '"' + '", "'.join(fields) + '"')
    f.close()
    return entries

def update_correct_fingerprints_from_csvs(simulation_project, **kwargs):
    correct_fingerprints = get_correct_fingerprint_store(simulation_project)
    # a fixed file order and a fixed timestamp: the same CSV files give the same store
    for csv_file in sorted(glob.glob(simulation_project.get_full_path("tests/fingerprint/*.csv"), recursive=True)):
        update_correct_fingerprints_from_csv(csv_file, correct_fingerprints, **kwargs)
    correct_fingerprints.write()
