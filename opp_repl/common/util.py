import curses.ascii
import datetime
import glob
import hashlib
import importlib
import inspect
import io
import IPython
import logging
import math
import os
import pandas
import platform
import pickle
import re
import signal
import subprocess
import sys
import threading
import time

pandas.set_option('display.float_format', lambda x: '%g' % x)

__sphinx_mock__ = True # ignore this module in documentation

COLOR_GRAY = "\033[90m"
COLOR_LIGHT_GRAY = "\033[38;2;200;200;200m"
COLOR_RED = "\033[1;31m"
COLOR_YELLOW = "\033[1;33m"
COLOR_CYAN = "\033[0;36m"
COLOR_GREEN = "\033[0;32m"
COLOR_MAGENTA = "\033[1;35m"
COLOR_RESET = "\033[0;0m"

STDOUT_LEVEL = 25  # between INFO (20) and WARNING (30)
STDERR_LEVEL = 35  # between WARNING (30) and ERROR (40)

class StopExecutionException(Exception):
    def __init__(self, **kwargs):
        super().__init__()
        self.value = kwargs.get("value", None)
        self.value_provided = "value" in kwargs

class TerminalInteractiveShell(IPython.terminal.interactiveshell.TerminalInteractiveShell):
    def _showtraceback(self, etype, evalue, stb):
        if isinstance(evalue, StopExecutionException):
            if evalue.value_provided:
                _logger.warning("Execution stopped programmatically by calling stop_execution(...) with:")
                print(evalue.value)
            else:
                _logger.warning("Execution stopped programmatically by calling stop_execution()")
            return None
        super()._showtraceback(etype, evalue, stb)

def stop_execution(*args):
    if len(args) == 0:
        raise StopExecutionException()
    else:
        raise StopExecutionException(value=args[0])

def enable_autoreload():
    ipython = IPython.get_ipython()
    ipython.run_line_magic("load_ext", "autoreload")
    ipython.run_line_magic("autoreload", "2")

def import_user_module():
    try:
        user = os.getlogin()
        user_module = importlib.import_module(user)
        main_module = sys.modules['__main__']
        for attr in dir(user_module):
            if not attr.startswith('_'):
                main_module.__dict__[attr] = getattr(user_module, attr)
    except ImportError as e:
        pass

_file_handler = None

class LocalLogger(logging.Logger):
    def stdout(self, message, *args, **kwargs):
        self._log(STDOUT_LEVEL, message, args, **kwargs)

    def stderr(self, message, *args, **kwargs):
        self._log(STDERR_LEVEL, message, args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self._log(logging.DEBUG, msg, args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._log(logging.INFO, msg, args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log(logging.WARNING, msg, args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log(logging.ERROR, msg, args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._log(logging.CRITICAL, msg, args, **kwargs)

    def log(self, level, msg, *args, **kwargs):
        self._log(level, msg, args, **kwargs)

    def handle(self, record):
        global _file_handler
        if _file_handler:
            _file_handler.handle(record)
        if self.isEnabledFor(record.levelno):
            super().handle(record)

logging.setLoggerClass(LocalLogger)

_logger = logging.getLogger(__name__)

_logging_initialized = False

def initialize_logging(log_level, external_command_log_level, log_file):
    global _file_handler, _logging_initialized
    if log_file:
        _file_handler = logging.FileHandler(log_file, mode="w")
        _file_handler.setLevel(logging.DEBUG)
        _file_handler.setFormatter(logging.Formatter('%(asctime)s\t%(name)s\t%(levelname)s\t%(message)s'))
    formatter = ColoredLoggingFormatter()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.handlers = []
    logger.addHandler(handler)
    logging.addLevelName(STDOUT_LEVEL, "STDOUT")
    logging.addLevelName(STDERR_LEVEL, "STDERR")
    set_python_log_level(log_level)
    set_external_command_log_level(external_command_log_level)
    _logging_initialized = True

def ensure_logging_initialized(log_level, external_command_log_level, log_file):
    if not _logging_initialized:
        initialize_logging(log_level, external_command_log_level, log_file)
        return True
    else:
        return False

def get_logging_formatter():
    logger = logging.getLogger()
    return logger.handlers[0].formatter

def set_python_log_level(log_level):
    logger = logging.getLogger()
    logger.setLevel(log_level)

def get_python_log_level():
    logger = logging.getLogger()
    return logger.getEffectiveLevel()

def set_external_command_log_level(log_level):
    logging.getLogger("py4j").setLevel(log_level)
    logging.getLogger("make").setLevel(log_level)
    logging.getLogger("opp_charttool").setLevel(log_level)
    logging.getLogger("opp_eventlogtool").setLevel(log_level)
    logging.getLogger("opp_featuretool").setLevel(log_level)
    logging.getLogger("opp_msgtool").setLevel(log_level)
    logging.getLogger("opp_nedtool").setLevel(log_level)
    logging.getLogger("opp_scavetool").setLevel(log_level)
    logging.getLogger("opp_makemake").setLevel(log_level)
    logging.getLogger("opp_run").setLevel(log_level)
    logging.getLogger("opp_run_dbg").setLevel(log_level)
    logging.getLogger("opp_run_release").setLevel(log_level)
    logging.getLogger("opp_run_sanitize").setLevel(log_level)
    logging.getLogger("opp_run_coverage").setLevel(log_level)
    logging.getLogger("opp_run_profile").setLevel(log_level)
    logging.getLogger("opp_test").setLevel(log_level)

def get_external_command_log_level():
    return logging.getLogger("opp_run").getEffectiveLevel()

def run_with_log_levels(func, *args, log_level=None, python_log_level=None, external_command_log_level=None, **kwargs):
    if python_log_level is None:
        python_log_level = python_log_level
    if external_command_log_level is None:
        external_command_log_level = python_log_level
    old_python_log_level = None
    old_external_command_log_level = None
    try:
        if python_log_level is not None:
            old_python_log_level = get_python_log_level()
            set_python_log_level(python_log_level)
        if external_command_log_level is not None:
            old_external_command_log_level = get_external_command_log_level()
            set_external_command_log_level(external_command_log_level)
        return func(*args, **kwargs)
    finally:
        if old_python_log_level is not None:
            set_python_log_level(old_python_log_level)
        if old_external_command_log_level is not None:
            set_external_command_log_level(old_external_command_log_level)

_default_build_argument = True

def get_default_build_argument():
    global _default_build_argument
    return _default_build_argument

def set_default_build_argument(value):
    global _default_build_argument
    _default_build_argument = value

def get_workspace_path(path):
    workspace_root = os.environ.get("WORKSPACE_ROOT")
    if workspace_root is None:
        workspace_root = os.path.realpath(os.path.dirname(__file__) + "/../../../..")
    return os.path.join(workspace_root, path)

def flatten(list):
    return [item for sublist in list for item in sublist]

def repr(object, properties=None):
    return f"{object.__class__.__name__}({', '.join([f'{prop}={value}' for prop, value in object.__dict__.items() if properties is None or prop in properties])})"

def coalesce(*values):
    """Return the first non-None value or None if all values are None"""
    return next((v for v in values if v is not None), None)

def convert_to_seconds(s):
    seconds_per_unit = {"ps": 1E-12, "ns": 1E-9, "us": 1E-6, "ms": 1E-3, "s": 1, "second": 1, "m": 60, "min": 60, "h": 3600, "hour": 3600, "d": 86400, "day": 86400, "w": 604800, "week": 604800}
    match = re.match(r"(-?[0-9]*\.?[0-9]*) *([a-zA-Z]+)", s)
    return float(match.group(1)) * seconds_per_unit[match.group(2)]

def write_object(file_name, object):
    with open(file_name, "wb") as file:
        pickle.dump(object, file)

def read_object(file_name):
    with open(file_name, "rb") as file:
        return pickle.load(file)

def hex_or_none(array):
    if array is None:
        return None
    else:
        return array.hex()

file_hashes = {}

def get_file_hash(file_path):
    global file_hashes
    modification_time = os.path.getmtime(file_path)
    if file_path in file_hashes:
        (stored_modification_time, stored_result) = file_hashes[file_path]
        if stored_modification_time == modification_time:
            return stored_result
    hasher = hashlib.sha256()
    hasher.update(open(file_path, "rb").read())
    result = hasher.digest()
    file_hashes[file_path] = (modification_time, result)
    return result

dependency_files = {}

def read_dependency_file(file_path):
    global dependency_files
    modification_time = os.path.getmtime(file_path)
    if file_path in dependency_files:
        (stored_modification_time, stored_result) = dependency_files[file_path]
        if stored_modification_time == modification_time:
            return stored_result
    result = {}
    file = open(file_path, "r", encoding="utf-8")
    text = file.read()
    text = text.replace("\\\n", "")
    text = text.replace("//", "/")
    for line in text.splitlines():
        match = re.match(r"(.+): (.+)", line)
        if match:
            targets = [e for e in match.group(1).strip().split(" ") if e != ""]
            for target in targets:
                result[target] = [e for e in match.group(2).strip().split(" ") if e != ""]
    file.close()
    dependency_files[file_path] = (modification_time, result)
    return result

def relative_error(old, new):
    if old != 0:
        return abs(new - old) / abs(old)
    else:
        return float("inf") if new != 0 else 0.0

def symmetric_relative_error(old, new):
    denom = abs(old) + abs(new)
    if denom == 0:
        return 0.0
    return 2 * (new - old) / denom

def unbounded_relative_error(old, new):
    e = symmetric_relative_error(old, new)
    if e >= 2:
        return float("inf")
    if e <= -2:
        return float("-inf")
    return 2.0 * math.atanh(e / 2.0)

def matches_filter(value, positive_filter, negative_filter, full_match):
    return ((re.fullmatch(positive_filter, value) if full_match else re.search(positive_filter, value)) is not None if positive_filter is not None else True) and \
           ((re.fullmatch(negative_filter, value) if full_match else re.search(negative_filter, value)) is None if negative_filter is not None else True)

def read_file(path):
    file = open(path, "r", encoding="utf-8")
    text = file.read()
    file.close()
    return text

class KeyboardInterruptHandler:
    def __init__(self):
        self.enabled = True
        self.old_handler = None
        self.received_signal = None

    def handle_disabled_keyboard_interrupt(self, sig, frame):
        self.received_signal = (sig, frame)
        _logger.debug("SIGINT received, delaying KeyboardInterrupt.")

    def handle_pending_keyboard_interrupt(self):
        if self.received_signal:
            self.old_handler(*self.received_signal)
            self.received_signal = None

    def disable(self):
        if self.enabled:
            self.enabled = False
            self.old_handler = signal.signal(signal.SIGINT, self.handle_disabled_keyboard_interrupt)
            self.received_signal = None

    def enable(self):
        if not self.enabled:
            self.enabled = True
            signal.signal(signal.SIGINT, self.old_handler)
            self.handle_pending_keyboard_interrupt()

class EnabledKeyboardInterrupts:
    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        if self.handler:
            try:
                self.handler.enable()
            except:
                if self.__exit__(*sys.exc_info()):
                    pass
                else:
                    raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handler:
            self.handler.disable()

class DisabledKeyboardInterrupts:
    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        if self.handler:
            try:
                self.handler.disable()
            except:
                if self.__exit__(*sys.exc_info()):
                    pass
                else:
                    raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handler:
            self.handler.enable()

def test_keyboard_interrupt_handler(a, b):
    handler = KeyboardInterruptHandler()
    with DisabledKeyboardInterrupts(handler):
        print("Disabled start")
        time.sleep(a)
        try:
            with EnabledKeyboardInterrupts(handler):
                print("Enabled start")
                time.sleep(b)
                print("Enabled end")
        except KeyboardInterrupt:
            print("Interrupted")
        print("Disabled end")

class ColoredLoggingFormatter(logging.Formatter):
    print_thread_name = False
    print_function_name = False

    COLORS = {
        logging.DEBUG: COLOR_GREEN,
        logging.INFO: COLOR_GREEN,
        logging.WARNING: COLOR_YELLOW,
        logging.ERROR: COLOR_RED,
        logging.CRITICAL: COLOR_RED,
        STDOUT_LEVEL: COLOR_GREEN,
        STDERR_LEVEL: COLOR_YELLOW,
    }

    def format(self, record):
        format = self.COLORS.get(record.levelno) + "%(levelname)s " + \
                 (COLOR_MAGENTA + "%(threadName)s " if self.print_thread_name else "") + \
                 COLOR_CYAN + "%(name)s " + \
                 (COLOR_MAGENTA + "%(funcName)s " if self.print_function_name else "") + \
                 COLOR_RESET + "%(message)s"
        formatter = logging.Formatter(format)
        return formatter.format(record)

def with_extended_thread_name(name, body):
    current_thread = threading.current_thread()
    old_name = current_thread.name
    try:
        current_thread.name = old_name + "/" + name
        body()
    finally:
        current_thread.name = old_name

def with_logger_level(logger, level, body):
    old_level = logger.getEffectiveLevel()
    try:
        logger.setLevel(level)
        body()
    finally:
        logger.setLevel(old_level)

class LoggerLevel(object):
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level

    def __enter__(self):
        self.old_level = self.logger.getEffectiveLevel()
        self.logger.setLevel(self.level)

    def __exit__(self, type, value, traceback):
        self.logger.setLevel(self.old_level)

class DebugLevel(LoggerLevel):
    def __init__(self, logger):
        super().__init__(self, logger, logging.DEBUG)

def run_command_with_logging(args, error_message=None, error_message_lines=20, nice=10, wait=True, **kwargs):
    logger = logging.getLogger(os.path.basename(args[0]))
    if logger.level == logging.NOTSET:
        logger.setLevel(get_external_command_log_level())
    def log_stream(stream, logger, lines):
        for line in iter(stream.readline, ""):
            logger(line.rstrip("\n"))
            lines.append(line)
        stream.close()
    stdout_lines = []
    stderr_lines = []
    _logger.debug(f"Running external command: {' '.join(args)}")
    process = subprocess.Popen(["nice", "-n", str(nice), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs)
    stdout_thread = threading.Thread(target=log_stream, args=(process.stdout, logger.stdout, stdout_lines))
    stderr_thread = threading.Thread(target=log_stream, args=(process.stderr, logger.stderr, stderr_lines))
    stdout_thread.start()
    stderr_thread.start()
    if wait:
        try:
            stdout_thread.join()
            stderr_thread.join()
            process.wait()
        except KeyboardInterrupt:
            process.kill()
            raise
        if process.returncode == -signal.SIGINT:
            raise KeyboardInterrupt()
        if error_message and process.returncode != 0:
            stderr_tail = "".join(stderr_lines[-error_message_lines:]).rstrip("\n")
            raise Exception(error_message + (":\n" + stderr_tail if stderr_tail else ""))
        return subprocess.CompletedProcess(args, process.returncode, "".join(stdout_lines), "".join(stderr_lines))
    else:
        return subprocess.CompletedProcess(args, 0, "", "")

def open_file_with_default_editor(file_path):
    if platform.system() == "Windows":
        os.startfile(file_path)
    elif platform.system() == "Darwin":  # macOS
        subprocess.run(["open", file_path])
    else:  # Linux/Unix
        subprocess.run(["xdg-open", file_path])

def set_data_frame_print_options_to_print_more_details():
    pandas.set_option('display.max_rows', None)
    pandas.set_option('display.max_columns', None)
    pandas.set_option("display.precision", 19)
    pandas.set_option('display.width', 1000)

def format_timedelta(td, *, precision = 3):
    """
    Format a timedelta without leading zero hours/minutes.

    Output style:
      - H:MM:SS(.fff...) if hours > 0
      - M:SS(.fff...)    if minutes > 0
      - S(.fff...)       otherwise
    Fractional seconds are rounded to `precision` decimal places and trailing
    zeros are removed. Uses exact integer microseconds (no float drift).

    Examples:
      0.12s   -> "0.12"
      45s     -> "45"
      65.1s   -> "1:05.1"
      3661s   -> "1:01:01"
    """
    if not isinstance(td, datetime.timedelta):
        raise TypeError("td must be a datetime.timedelta")

    if precision < 0 or precision > 6:
        raise ValueError("precision must be between 0 and 6")

    # Exact total microseconds (timedelta stores days/seconds/microseconds as ints)
    total_us = ((td.days * 86400 + td.seconds) * 1_000_000) + td.microseconds

    sign = "-" if total_us < 0 else ""
    total_us = abs(total_us)

    # Round to requested precision
    if precision < 6:
        factor = 10 ** (6 - precision)  # e.g. precision=3 -> 1000us (ms)
        total_us = (total_us + factor // 2) // factor * factor

    # Break down
    total_seconds, us = divmod(total_us, 1_000_000)
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)

    # Build base time string without leading units
    if h:
        base = f"{h}:{m:02d}:{s:02d}"
    elif m:
        base = f"{m}:{s:02d}"
    else:
        base = f"{s}"

    # Fractional part
    frac = ""
    if precision and us:
        frac_digits = f"{us:06d}"[:precision]  # take leading digits after rounding
        frac_digits = frac_digits.rstrip("0")
        if frac_digits:
            frac = "." + frac_digits

    return sign + base + frac

def combine_signatures(*funcs):
    """Build a combined :class:`inspect.Signature` from multiple callables.

    This is useful for top-level convenience functions that accept ``**kwargs``
    and forward them through a chain of inner functions.  Setting
    ``func.__signature__`` to the combined signature enables IDE and IPython
    tab-completion for every accepted keyword argument.

    Semantics:

    * Explicit parameters are collected from each callable in order
      (excluding ``self``, ``*args``, and ``**kwargs``).
    * If the same parameter name appears in more than one callable, the
      **first** occurrence wins (i.e. the outermost / closest-to-user
      function determines the default and annotation).
    * Every parameter in the combined signature is made **keyword-only**.

    Example::

        def inner(*, a=1, b=2, **kwargs): ...
        def outer(**kwargs):
            return inner(**kwargs)
        outer.__signature__ = combine_signatures(outer, inner)

    Parameters:
        funcs: One or more callables whose signatures should be merged.

    Returns:
        inspect.Signature: A new signature containing the ordered union of
        all keyword-only parameters.
    """
    seen = set()
    params = []
    for func in funcs:
        try:
            sig = inspect.signature(func, follow_wrapped=False)
        except (ValueError, TypeError):
            continue
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if name not in seen:
                seen.add(name)
                params.append(param.replace(kind=inspect.Parameter.KEYWORD_ONLY))
    return inspect.Signature(params)

def is_running_in_sandbox():
    sentinel = "/.opp_sandbox"
    if not os.path.exists(sentinel):
        return False
    # Verify that the sentinel file is actually read-only (ro-bind in the sandbox).
    try:
        fd = os.open(sentinel, os.O_WRONLY)
        os.close(fd)
        return False
    except OSError:
        pass
    return True

_KEY_COLUMNS = ['experiment', 'measurement', 'replication', 'module', 'name']

class ScalarComparisonResult:
    """Result of comparing two scalar DataFrames.

    Attributes:
        df_1 (pd.DataFrame): The first input DataFrame.
        df_2 (pd.DataFrame): The second input DataFrame.
        is_equal (bool): ``True`` when the two DataFrames are equal.
        identical (pd.DataFrame): Rows present and equal in both DataFrames.
        different (pd.DataFrame): Rows that differ, sorted by descending
            ``|relative_error|``.  Contains the key columns plus
            ``value_1``, ``value_2``, and the requested error columns.
    """

    def __init__(self, df_1, df_2, is_equal, identical, different):
        self.df_1 = df_1
        self.df_2 = df_2
        self.is_equal = is_equal
        self.identical = identical
        self.different = different

    def __repr__(self):
        n1, n2 = len(self.df_1), len(self.df_2)
        ni, nd = len(self.identical), len(self.different)
        return f"ScalarComparisonResult({n1} and {n2} TOTAL, {ni} IDENTICAL, {nd} DIFFERENT)"

    def refilter(self, **kwargs):
        """Recompute the comparison with different filter parameters.

        Accepts the same filter keyword arguments as
        :py:func:`compare_scalar_dataframes` (``name_filter``,
        ``exclude_name_filter``, ``module_filter``, ``exclude_module_filter``,
        ``full_match``, ``unbounded_relative_error_threshold``).

        Returns:
            ScalarComparisonResult: A new comparison result with the updated filters applied.
        """
        return compare_scalar_dataframes(self.df_1, self.df_2, **kwargs)

def compare_scalar_dataframes(
    df_1,
    df_2,
    suffixes=('_1', '_2'),
    name_filter=None,
    exclude_name_filter=None,
    module_filter=None,
    exclude_module_filter=None,
    full_match=False,
    unbounded_relative_error_threshold=None,
):
    """Compare two scalar result DataFrames and return the differences.

    Both DataFrames must contain at least the columns ``experiment``,
    ``measurement``, ``replication``, ``module``, ``name``, and ``value``.

    The *different* DataFrame always includes a ``relative_error`` column
    (simple ``|v2-v1|/|v1|``) and an ``unbounded_relative_error`` column
    (symmetric atanh-based metric).  Rows are sorted by descending
    ``|unbounded_relative_error|``.

    Parameters:
        df_1 (pd.DataFrame): First (or *stored*/*baseline*) DataFrame.
        df_2 (pd.DataFrame): Second (or *current*) DataFrame.
        suffixes (tuple): Column suffixes used when merging the ``value``
            column (default ``('_1', '_2')``).
        name_filter (str or None): Regex to include only matching ``name`` rows.
        exclude_name_filter (str or None): Regex to exclude matching ``name`` rows.
        module_filter (str or None): Regex to include only matching ``module`` rows.
        exclude_module_filter (str or None): Regex to exclude matching ``module`` rows.
        full_match (bool): If ``True`` filters use ``re.fullmatch``; otherwise ``re.search``.
        unbounded_relative_error_threshold (float or None): If set, rows whose
            ``|unbounded_relative_error|`` is below this threshold are
            dropped from the *different* result.

    Returns:
        ScalarComparisonResult: Container with ``df_1``, ``df_2``,
        ``is_equal``, ``identical``, and ``different`` attributes.
    """
    value_col_1 = 'value' + suffixes[0]
    value_col_2 = 'value' + suffixes[1]

    if df_1.equals(df_2):
        return ScalarComparisonResult(
            df_1=df_1,
            df_2=df_2,
            is_equal=True,
            identical=pandas.merge(df_1, df_2, how="inner"),
            different=pandas.DataFrame(),
        )

    merged = df_1.merge(df_2, on=_KEY_COLUMNS, how='outer', suffixes=suffixes)

    df = merged[
        (merged[value_col_1].isna() & merged[value_col_2].notna()) |
        (merged[value_col_1].notna() & merged[value_col_2].isna()) |
        (merged[value_col_1] != merged[value_col_2])
    ].dropna(subset=[value_col_1, value_col_2], how='all').copy()

    # --- error columns (always computed) ----------------------------------
    df["absolute_error"] = df.apply(
        lambda row: abs(row[value_col_2] - row[value_col_1]), axis=1)
    df["relative_error"] = df.apply(
        lambda row: relative_error(row[value_col_1], row[value_col_2]), axis=1)
    df["unbounded_relative_error"] = df.apply(
        lambda row: unbounded_relative_error(row[value_col_1], row[value_col_2]), axis=1)

    # --- filtering --------------------------------------------------------
    if name_filter is not None or exclude_name_filter is not None or \
       module_filter is not None or exclude_module_filter is not None:
        df = df[df.apply(
            lambda row: matches_filter(row["name"], name_filter, exclude_name_filter, full_match) and
                        matches_filter(row["module"], module_filter, exclude_module_filter, full_match),
            axis=1)]

    # --- threshold --------------------------------------------------------
    if unbounded_relative_error_threshold is not None and not df.empty:
        df = df[df["unbounded_relative_error"].abs() >= unbounded_relative_error_threshold]

    # --- sort by error magnitude ------------------------------------------
    df = df.loc[df["unbounded_relative_error"].abs().sort_values(ascending=False).index]

    return ScalarComparisonResult(
        df_1=df_1,
        df_2=df_2,
        is_equal=False,
        identical=pandas.merge(df_1, df_2, how="inner"),
        different=df,
    )
