# NOTICE

This repository is a personal working copy derived from
[LuwuDynamics/xgoduck_runtime_arduino](https://github.com/LuwuDynamics/xgoduck_runtime_arduino),
branched at commit `9dc3678` and carrying local modifications. `git log` and
`git diff 9dc3678` show every change.

## Upstream licensing status

Upstream states, in `THIRD_PARTY_NOTICES.md` and its README, that **no overall
license has been declared for the runtime repository or for its
`xgoduck_*.onnx` policy assets**. The texts under `LICENSES/` cover third-party
components only:

| Component | License |
| --- | --- |
| Microduck runtime (Pollen Robotics) | Apache License 2.0 |
| Arduino RouterBridge / RPCLite | Mozilla Public License 2.0 |

Portions authored by Luwu Dynamics remain under their author's copyright.
Nothing in this repository changes, broadens, or relicenses those terms, and
this file does not declare a license for the code as a whole.

## What this copy changes

Local modifications relative to `9dc3678` are listed by `git diff 9dc3678`.
They include the walking home pose, the fall-detection threshold, gamepad
support, a startup default pose, and a two-slot walk model switch. Modified
files carry no copyright claim beyond their original authors'.

## Intended use

Until the upstream author publishes a license or grants permission, treat this
copy as personal and educational use rather than as redistributable software.
Permission enquiries can go to the address published in the upstream hardware
repository, hello@xgorobot.com, or through the upstream issue tracker.
