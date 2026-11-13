> [繁體中文](README.md) | [English](README.en.md)

# Nous Duck

Build a full-size (100%) [Open Duck Mini v2](../README.md) and connect it to [Nous (AIOS)](https://github.com/pcpcchen-coder/AIOS): **Nous is the brain, the duck is the body.**

This directory holds all of this fork's own development. Upstream files are never modified (see the root [`CLAUDE.md`](../CLAUDE.md), Traditional Chinese only).

## Current status (2026-11-13)

| Item | Status |
|---|---|
| Printing | All 51 original parts printed ([progress](docs/build_log/print_status.md)) |
| Procurement | Sourcing hardware ([checklist and suppliers](docs/build_log/README.md)) |
| Assembly | Not started |
| Software | The assembly viewer's data pipeline is done: it computes the placement of 138 parts from the upstream CAD and maps all 14 servo IDs; unit tests and a MuJoCo cross-check pass ([validation record](docs/validation/viewer-pipeline-2026-11-13.md), Traditional Chinese only). The front end and all other modules are still "Planned" |
| Design | Mobile-companion requirement [R-001](docs/requirements/R-001-mobile-companion.md) (navigation, mobile conversation, wake-and-find, auto-docking) and ADR-0002 to 0006 (including switchable privacy settings) are drafts or partly accepted; phases are in the [roadmap](docs/roadmap.md) (Traditional Chinese only) |
| Hardware validation | None |

## Division of work

- **Nous (Mac mini)**: voice, vision, memory, decisions.
- **Duck (Pi Zero 2 W body board plus a Pi 4 perception board)**: gait, motion, safety (safety decisions happen only on the duck). After R-001 it also adds indoor localization and navigation, audio capture and playback, a wake word, finding people, and automatic docking.
- The two sides communicate only through the versioned JSON Schemas in [`protocol/`](protocol/README.en.md).

See the [architecture](docs/architecture.md) and [ADR-0001](docs/adr/ADR-0001-duck-role-in-nous.md) (both Traditional Chinese only).

## Directories

| Path | Contents | Status |
|---|---|---|
| [`docs/handoff/`](docs/handoff/README.md) | Handoff summary, environment survey, ChatGPT conversation log, upstream BOM | Done |
| [`docs/requirements/`](docs/requirements/README.md) | Requirement records | R-001 |
| [`docs/architecture.md`](docs/architecture.md) | Division of work and data flow between the duck and Nous | Draft |
| [`docs/roadmap.md`](docs/roadmap.md) | Phases and gates, decisions waiting for the owner | Draft |
| [`docs/adr/`](docs/adr/README.md) | Architecture decision records | ADR-0001 to 0006 |
| [`docs/build_log/`](docs/build_log/README.md) | Printing, procurement, assembly, and calibration progress | Printing complete, procurement underway |
| [`docs/validation/`](docs/validation/README.md) | Hardware and test records | No records yet |
| [`assembly_viewer/`](assembly_viewer/README.md) | ① Offline single-HTML 3D assembly viewer (first deliverable) | Pipeline done; BOM, steps, and front end planned |
| [`protocol/`](protocol/README.en.md) | ② duck-link protocol (JSON Schema) | Planned |
| [`robot/`](robot/README.md) | ③ On-board software (Pi Zero 2 W, Python) | Planned |
| [`nous_adapter/`](nous_adapter/README.en.md) | ④ `app.duck.*` adapter and terminal to move into AIOS (TypeScript) | Planned |
| [`sim/`](sim/README.md) | ⑤ MuJoCo simulation | Planned |
| [`hardware/`](hardware/README.md) | ⑥ Modifications: MG995 head prototype, expression modules, wiring, sensor head, perception board, charging dock | Planned; the [charging dock](hardware/dock/README.md) is design v0 (STL files generated; not printed, not tested on hardware; docs in Traditional Chinese) |
| [`tools/`](tools/README.md) | Development tools (upstream-untouched check, ChatGPT share-page converter) | Usable |

Documents other than this README and the `protocol/` and `nous_adapter/` READMEs are in Traditional Chinese only.

## Main hardware

- Feetech STS3215-C001 (7.4 V, 1:345) × 14. IDs: right leg 10–14, left leg 20–24, neck and head 30–33.
- Raspberry Pi Zero 2 W, Waveshare Bus Servo Adapter, BNO055 IMU, 2S 18650 battery (per the [upstream BOM](docs/handoff/upstream_bom.csv)).
- The five MG995 servos on hand are used only for a head prototype.
- R-001 additions (planned): a Raspberry Pi 4 perception board, a Waveshare AR0144 stereo camera, a standard reSpeaker XVF3800 USB 4-Mic Array (the same model FamilyRecorder uses; camera on the head, microphone array on the body), a physical privacy switch, RGB eye lights, rear charging contacts, and a charging dock.

## Dependencies

The on-board runtime uses [apirrone/Open_Duck_Mini_Runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime) (`v2`), installed with pip from git at a pinned commit. It is not forked for now.

## Syncing with upstream

```bash
git remote add upstream https://github.com/apirrone/Open_Duck_Mini.git   # first time only
git fetch upstream
git merge upstream/v2
bash nous_duck/tools/check_upstream_untouched.sh upstream/v2
```
