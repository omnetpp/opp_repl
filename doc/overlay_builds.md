# Overlay Builds

Overlay builds use `fuse-overlayfs` to create a writable layer on top
of a read-only source tree, allowing out-of-tree builds without
modifying the original checkout.

Projects with `overlay_name` in their `.opp` file use overlays automatically.

## Python API

```python
from opp_repl.simulation.overlay import *

list_overlays()          # list overlay names under the build root
cleanup_overlays()       # unmount all overlays
clear_build_root()       # unmount and remove all overlay data
```
