"""
Managing simulation workspaces containing multiple simulation projects.

A :py:class:`SimulationWorkspace` holds registries for
:py:class:`~opp_repl.simulation.project.OmnetppProject` and
:py:class:`~opp_repl.simulation.project.SimulationProject` instances.
It discovers projects from ``.opp`` descriptor files found under a
workspace directory (e.g. ``~/workspace``).

Pre-loaded variables
--------------------

When the opp_repl REPL starts, a default workspace is created automatically
and can be accessed via ``get_default_simulation_workspace()``.

All ``.opp`` files found under ``~/workspace`` are loaded, so simulation
projects are immediately available without any setup.  Use the convenience
functions below instead of accessing the workspace directly:

- ``get_simulation_project("simu5g")`` — look up a project by name
- ``get_default_simulation_project()`` — the project matching the current
  working directory (set automatically at startup)
- ``get_default_simulation_workspace().get_simulation_projects()`` — dict of
  ``(name, version)`` → :py:class:`~opp_repl.simulation.project.SimulationProject`

Example usage::

    simu5g = get_simulation_project("simu5g")
    print(simu5g.root_folder_environment_variable_relative_folder)
    print(simu5g.get_simulation_configs())

    ws = get_default_simulation_workspace()
    for (name, version), proj in ws.get_simulation_projects().items():
        print(name, proj.root_folder_environment_variable_relative_folder)

Loading additional projects
---------------------------

To register projects from outside the default workspace::

    load_opp_file("/path/to/project.opp")
    load_workspace("/other/workspace")
"""

import ast
import glob
import logging
import os

from opp_repl.simulation.project import OmnetppProject, SimulationProject

_logger = logging.getLogger(__name__)

class SimulationWorkspace:
    """Holds registries for :py:class:`OmnetppProject` and
    :py:class:`SimulationProject` instances and provides methods to discover,
    load, and resolve projects from ``.opp`` descriptor files.

    A default module-level instance backs the module-level helper
    functions so that existing code continues to work unchanged.
    """

    def __init__(self, workspace_path=None):
        self._workspace_path = workspace_path
        self._omnetpp_projects = {}
        self._simulation_projects = {}
        self._default_project = None
        if workspace_path is not None:
            self.load()

    def get_workspace_path(self):
        return self._workspace_path

    def get_omnetpp_projects(self):
        return self._omnetpp_projects

    def get_simulation_projects(self):
        return self._simulation_projects

    # -- omnetpp project registry ----------------------------------------

    def get_omnetpp_project_names(self):
        """Return a sorted list of registered OMNeT++ project names."""
        return sorted(set(name for name, version in self._omnetpp_projects.keys()))

    def get_omnetpp_project(self, name, version=None):
        return self._omnetpp_projects[(name, version)]

    def set_omnetpp_project(self, name, version, project):
        self._omnetpp_projects[(name, version)] = project

    def define_omnetpp_project(self, name, version=None, **kwargs):
        from opp_repl.simulation.project import get_default_omnetpp_project, set_default_omnetpp_project
        project = OmnetppProject(version=version, **kwargs)
        project.name = name
        self.set_omnetpp_project(name, version, project)
        return project

    # -- simulation project registry -------------------------------------

    def get_simulation_project_names(self):
        """Return a sorted list of registered simulation project names."""
        return sorted(set(name for name, version in self._simulation_projects.keys()))

    def get_simulation_project(self, name, version=None):
        return self._simulation_projects[(name, version)]

    def set_simulation_project(self, name, version, simulation_project):
        self._simulation_projects[(name, version)] = simulation_project

    def define_simulation_project(self, name, version=None, **kwargs):
        simulation_project = SimulationProject(name, version, **kwargs)
        simulation_project._workspace = self
        self.set_simulation_project(name, version, simulation_project)
        return simulation_project

    # -- default project -------------------------------------------------

    def get_default_simulation_project(self):
        if self._default_project is None:
            raise Exception("No default simulation project is set")
        return self._default_project

    def set_default_simulation_project(self, project):
        self._default_project = project
        from opp_repl.simulation.project import get_default_omnetpp_project, set_default_omnetpp_project
        if get_default_omnetpp_project() is None and project is not None:
            omnetpp_project = project.get_omnetpp_project()
            if omnetpp_project is None and ("omnetpp", None) in self._omnetpp_projects:
                omnetpp_project = self._omnetpp_projects[("omnetpp", None)]
            if omnetpp_project is not None:
                set_default_omnetpp_project(omnetpp_project)

    def determine_default_simulation_project(self, name=None, version=None, required=True, **kwargs):
        if name:
            simulation_project = self.get_simulation_project(name, version)
        else:
            simulation_project = self.find_simulation_project_from_current_working_directory(**kwargs)
        if simulation_project is None:
            if required:
                raise Exception("No enclosing simulation project is found from current working directory, and no simulation project is specified explicitly")
        else:
            _logger.info(f"Default project is set to {simulation_project.name}")
        self.set_default_simulation_project(simulation_project)
        return simulation_project

    def find_simulation_project_from_current_working_directory(self, **kwargs):
        current_working_directory = os.getcwd()
        path = current_working_directory
        while True:
            project_file_name = os.path.join(path, ".opp")
            if os.path.exists(project_file_name):
                return self._resolve_simulation_project_from_file(project_file_name, root_folder=path)
            parent_path = os.path.abspath(os.path.join(path, os.pardir))
            if path == parent_path:
                break
            else:
                path = parent_path
        for k, simulation_project in self._simulation_projects.items():
            full_path = simulation_project.get_full_path(".")
            if full_path is not None and current_working_directory.startswith(os.path.realpath(full_path)):
                return simulation_project

    # -- resolve ---------------------------------------------------------

    def resolve_simulation_project(self, designator):
        """
        Resolves a project designator string to a :py:class:`SimulationProject`.

        The designator can take several forms:

        - **name** — lookup by registered name (e.g. ``"inet"``)
        - **name:version** — lookup by registered name and version (e.g. ``"inet:4.5"``)
        - **folder path** — absolute or relative path to a project folder (e.g. ``"../inet-baseline"``, ``"/home/user/inet-old"``)
        - **git:ref** — (TODO) checkout a git ref in a worktree and resolve

        When a folder path is given, the function first checks whether any registered
        project already lives at that location.  If not, it looks for a ``.opp``
        project descriptor file in the folder and auto-registers the project.

        Parameters:
            designator (string or None):
                The project designator string.  If ``None``, the default project is
                returned.

        Returns (:py:class:`SimulationProject`):
            the resolved simulation project.
        """
        if designator is None:
            return self.get_default_simulation_project()

        # TODO: git:ref — create a git worktree for the ref and resolve from the worktree folder
        if designator.startswith('git:'):
            raise ValueError(f"git: designator is not yet implemented: {designator}")

        # absolute or relative file or folder path
        if designator.startswith(('/', '.', '~')):
            path = os.path.expanduser(os.path.abspath(designator))
            if os.path.isfile(path):
                return self._resolve_simulation_project_from_file(path, root_folder=os.path.dirname(path))
            return self._resolve_simulation_project_from_folder(path)

        # name:version
        if ':' in designator:
            name, version = designator.split(':', 1)
            return self.get_simulation_project(name, version)

        # plain name
        return self.get_simulation_project(designator, None)

    def _resolve_simulation_project_from_folder(self, path):
        path = os.path.realpath(path)
        if not os.path.isdir(path):
            raise ValueError(f"Not a directory: {path}")
        for (name, version), project in self._simulation_projects.items():
            if os.path.realpath(project.get_full_path(".")) == path:
                return project
        project_file = os.path.join(path, ".opp")
        if os.path.exists(project_file):
            return self._resolve_simulation_project_from_file(project_file, root_folder=path)
        raise ValueError(f"No simulation project found at {path} (no registered project or .opp file)")

    def _resolve_simulation_project_from_file(self, path, **kwargs):
        class_name, file_kwargs = _parse_opp_file(path)
        if class_name != "SimulationProject":
            raise ValueError(f"{path}: expected SimulationProject, got {class_name}")
        file_kwargs.update(kwargs)
        return self.define_simulation_project(**file_kwargs)

    # -- .opp file loading -----------------------------------------------

    def load_opp_file(self, path):
        """Load ``.opp`` file(s) and register the project(s).

        *path* may be a single file path **or** a glob pattern (any string
        containing ``*``, ``?``, or ``[``).  When a glob pattern is given,
        all matching files are loaded in two passes (OmnetppProject first,
        then SimulationProject) just like :py:meth:`load`.

        Returns:
            A single :py:class:`OmnetppProject` or
            :py:class:`SimulationProject` when *path* refers to exactly one
            file, or a ``dict`` mapping project names to project objects when
            a glob pattern is used.
        """
        if glob.has_magic(path):
            return self._load_opp_glob(path)
        return self._load_single_opp_file(path)

    def _load_single_opp_file(self, path):
        """Load one ``.opp`` file and register the project."""
        class_name, kwargs = _parse_opp_file(path)
        _resolve_opp_paths(path, kwargs)
        if class_name == "OmnetppProject":
            name = kwargs.pop("name", os.path.basename(os.path.dirname(os.path.abspath(path))))
            return self.define_omnetpp_project(name, **kwargs)
        else:
            kwargs.setdefault("name", os.path.splitext(os.path.basename(path))[0])
            return self.define_simulation_project(**kwargs)

    def _load_opp_glob(self, pattern):
        """Load all ``.opp`` files matching *pattern* (two-pass)."""
        opp_files = sorted(glob.glob(pattern, recursive=True))
        if not opp_files:
            _logger.warning("No .opp files matched pattern: %s", pattern)
            return {}
        parsed = []
        for opp_file in opp_files:
            try:
                class_name, kwargs = _parse_opp_file(opp_file)
                _resolve_opp_paths(opp_file, kwargs)
                parsed.append((opp_file, class_name, kwargs))
            except ValueError as e:
                _logger.warning("Skipping %s: %s", opp_file, e)
        results = {}
        for opp_file, class_name, kwargs in parsed:
            if class_name == "OmnetppProject":
                name = kwargs.pop("name", os.path.basename(os.path.dirname(os.path.abspath(opp_file))))
                proj = self.define_omnetpp_project(name, **kwargs)
                results[name] = proj
                _logger.info("Loaded omnetpp project '%s' from %s", name, opp_file)
        for opp_file, class_name, kwargs in parsed:
            if class_name == "SimulationProject":
                kwargs.setdefault("name", os.path.splitext(os.path.basename(opp_file))[0])
                proj = self.define_simulation_project(**kwargs)
                results[proj.name] = proj
                _logger.info("Loaded simulation project '%s' from %s", proj.name, opp_file)
        return results

    def load(self, workspace_path=None):
        """Scan *workspace_path* for ``*.opp`` files and register all projects.

        Omnetpp projects are loaded first so that simulation projects can
        reference them by name via ``omnetpp_project="..."``.

        Returns:
            dict: ``{name: project}`` for all loaded projects.
        """
        workspace_path = workspace_path or self._workspace_path
        if workspace_path is None:
            raise ValueError("No workspace path specified")
        workspace_path = os.path.expanduser(workspace_path)
        opp_files = glob.glob(os.path.join(workspace_path, "*", "*.opp"))
        parsed = []
        for opp_file in sorted(opp_files):
            try:
                class_name, kwargs = _parse_opp_file(opp_file)
                _resolve_opp_paths(opp_file, kwargs)
                parsed.append((opp_file, class_name, kwargs))
            except ValueError as e:
                _logger.warning("Skipping %s: %s", opp_file, e)
        results = {}
        # Pass 1: OmnetppProject (no dependencies)
        for opp_file, class_name, kwargs in parsed:
            if class_name == "OmnetppProject":
                name = kwargs.pop("name", os.path.basename(os.path.dirname(os.path.abspath(opp_file))))
                proj = self.define_omnetpp_project(name, **kwargs)
                results[name] = proj
                _logger.info("Loaded omnetpp project '%s' from %s", name, opp_file)
        # Pass 2: SimulationProject (may reference omnetpp by name — resolved lazily)
        for opp_file, class_name, kwargs in parsed:
            if class_name == "SimulationProject":
                kwargs.setdefault("name", os.path.splitext(os.path.basename(opp_file))[0])
                proj = self.define_simulation_project(**kwargs)
                results[proj.name] = proj
                _logger.info("Loaded simulation project '%s' from %s", proj.name, opp_file)
        return results

# -- .opp file parser (module-level utility) -----------------------------

def _parse_opp_file(path):
    """Parse a restricted-Python ``.opp`` file and return (class_name, kwargs).

    The file must contain a single expression of the form::

        OmnetppProject(key=value, ...)
        SimulationProject(key=value, ...)

    All values must be literals (strings, numbers, booleans, None, lists, dicts).
    No imports, no variable references, no arbitrary code.

    Returns:
        tuple: (class_name, dict_of_keyword_arguments)

    Raises:
        ValueError: if the file does not match the restricted format.
    """
    with open(path) as f:
        source = f.read()
    tree = ast.parse(source, filename=path, mode="eval")
    node = tree.body
    if not isinstance(node, ast.Call):
        raise ValueError(f"{path}: expected a single constructor call, got {type(node).__name__}")
    if not isinstance(node.func, ast.Name):
        raise ValueError(f"{path}: expected a simple name like OmnetppProject(...), got {ast.dump(node.func)}")
    class_name = node.func.id
    if class_name not in ("OmnetppProject", "SimulationProject"):
        raise ValueError(f"{path}: unknown project type '{class_name}', expected OmnetppProject or SimulationProject")
    if node.args:
        raise ValueError(f"{path}: positional arguments are not allowed, use keyword arguments only")
    kwargs = {}
    for kw in node.keywords:
        try:
            kwargs[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError) as e:
            raise ValueError(f"{path}: parameter '{kw.arg}' must be a literal value: {e}")
    return class_name, kwargs

_OPP_PATH_KEYS = ("root_folder", "overlay_build_root", "opp_env_workspace")

def _resolve_opp_paths(opp_file_path, kwargs):
    """Resolve relative path values in *kwargs* against the ``.opp`` file's directory."""
    opp_dir = os.path.dirname(os.path.abspath(opp_file_path))
    for key in _OPP_PATH_KEYS:
        value = kwargs.get(key)
        if value is not None and not os.path.isabs(value):
            kwargs[key] = os.path.normpath(os.path.join(opp_dir, value))

# -- Default workspace and module-level shims ----------------------------

_default_simulation_workspace = None

def get_default_simulation_workspace():
    global _default_simulation_workspace
    if _default_simulation_workspace is None:
        _default_simulation_workspace = SimulationWorkspace()
    return _default_simulation_workspace

def set_default_simulation_workspace(workspace):
    global _default_simulation_workspace
    _default_simulation_workspace = workspace

def get_omnetpp_project_names():
    """Return a sorted list of registered OMNeT++ project names."""
    return get_default_simulation_workspace().get_omnetpp_project_names()

def get_omnetpp_project(name, version=None):
    return get_default_simulation_workspace().get_omnetpp_project(name, version)

def set_omnetpp_project(name, version, project):
    get_default_simulation_workspace().set_omnetpp_project(name, version, project)

def define_omnetpp_project(name, version=None, **kwargs):
    return get_default_simulation_workspace().define_omnetpp_project(name, version, **kwargs)

def get_simulation_project_names():
    """Return a sorted list of registered simulation project names."""
    return get_default_simulation_workspace().get_simulation_project_names()

def get_simulation_project(name, version=None):
    """
    Returns a defined simulation project for the provided name and version.

    Parameters:
        name (string):
            The name of the simulation project.

        version (string or None):
            The version of the simulation project. If unspecified, then the latest version is returned.

    Returns (py:class:`SimulationProject` or None):
        a simulation project.
    """
    return get_default_simulation_workspace().get_simulation_project(name, version)

def set_simulation_project(name, version, simulation_project):
    get_default_simulation_workspace().set_simulation_project(name, version, simulation_project)

def define_simulation_project(name, version=None, **kwargs):
    """
    Defines a simulation project for the provided name, version and additional parameters.

    Parameters:
        name (string):
            The name of the simulation project.

        version (string or None):
            The version of the simulation project. If unspecified, then no version is assumed.

        kwargs (dict):
            Additional parameters are inherited from the constructor of :py:class:`SimulationProject`.

    Returns (:py:class:`SimulationProject`):
        the new simulation project.
    """
    return get_default_simulation_workspace().define_simulation_project(name, version, **kwargs)

def find_simulation_project_from_current_working_directory(**kwargs):
    return get_default_simulation_workspace().find_simulation_project_from_current_working_directory(**kwargs)

def determine_default_simulation_project(name=None, version=None, required=True, **kwargs):
    return get_default_simulation_workspace().determine_default_simulation_project(name, version, required, **kwargs)

def get_default_simulation_project():
    """
    Returns the currently selected default simulation project from the set of defined simulation projects. The default
    simulation project is usually the one that is above the current working directory.

    Returns (:py:class:`SimulationProject`):
        a simulation project.
    """
    return get_default_simulation_workspace().get_default_simulation_project()

def set_default_simulation_project(project):
    """
    Changes the currently selected default simulation project from the set of defined simulation projects.

    Parameters:
        project (:py:class:`SimulationProject`):
            The simulation project that is set as the default.

    Returns (None):
        nothing.
    """
    get_default_simulation_workspace().set_default_simulation_project(project)

def resolve_simulation_project(designator):
    """
    Resolves a project designator string to a :py:class:`SimulationProject`.

    See :py:meth:`SimulationWorkspace.resolve_simulation_project` for details.
    """
    return get_default_simulation_workspace().resolve_simulation_project(designator)

def load_opp_file(path):
    """Load ``.opp`` file(s) and register the project(s) in the default workspace.

    *path* can be a single file or a glob pattern (e.g.
    ``"/home/user/workspace/omnetpp/samples/*/*.opp"``).
    """
    return get_default_simulation_workspace().load_opp_file(path)

def get_omnetpp_project_variables():
    """Return a dict mapping ``{name}_project`` to each loaded OMNeT++ project.

    Hyphens and dots in project names are replaced with underscores so that the
    keys are valid Python identifiers.  This is intended to be injected into the
    REPL namespace at startup, e.g.::

        globals().update(get_omnetpp_project_variables())
    """
    result = {}
    for name in get_omnetpp_project_names():
        var_name = name.replace('-', '_').replace('.', '_') + '_project'
        result[var_name] = get_omnetpp_project(name)
    return result

def get_simulation_project_variables():
    """Return a dict mapping ``{name}_project`` to each loaded simulation project.

    Hyphens and dots in project names are replaced with underscores so that the
    keys are valid Python identifiers.  This is intended to be injected into the
    REPL namespace at startup, e.g.::

        globals().update(get_simulation_project_variables())
    """
    result = {}
    for name in get_simulation_project_names():
        var_name = name.replace('-', '_').replace('.', '_') + '_project'
        result[var_name] = get_simulation_project(name)
    return result

def get_simulation_project_variable_names():
    """Return a sorted list of the variable names generated by :py:func:`get_simulation_project_variables`.

    Each name has the form ``{project_name}_project`` with hyphens and dots
    replaced by underscores.
    """
    return sorted(name.replace('-', '_').replace('.', '_') + '_project' for name in get_simulation_project_names())

def load_workspace(workspace_path):
    """Scan *workspace_path* for ``*.opp`` files and register all projects in the default workspace."""
    return get_default_simulation_workspace().load(workspace_path)
