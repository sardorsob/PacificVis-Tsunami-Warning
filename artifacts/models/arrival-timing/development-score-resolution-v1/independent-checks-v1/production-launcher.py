"""One fixed numerical job; dry metadata admission unless --execute is supplied."""

# pyright: basic
import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

ROOT = Path("/Users/sobirov/Workspace/Projects/Tsunami-Warning-Times")
ORIGINAL_SHA = "8369712a58ef2d1c28527a6850fb8769b684147bbad0c12bf469d3e03907ace8"
SCRIPT = Path(__file__).resolve()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def payload(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def write(path, value):
    with path.open("xb") as f:
        f.write(payload(value))


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root)


def admit(root):
    require(root == ROOT.resolve(), "canonical project root required")
    sys.path.insert(0, str(root))
    from analysis.arrival import model_development_score_resolution as m
    from scripts import run_arrival_development_completion as completion

    old = completion.old
    admission = m.verify_gate(root)  # Metadata-only; never load_case/cold_replay.
    original = old.admit(root, "check")
    old.previous._require(admission["files"], original["files"])
    gate = admission["gate"]
    require(
        gate.get("original_state_sha256") == ORIGINAL_SHA,
        "literal retained original state SHA required",
    )
    require(
        gate.get("launcher_sha256") == sha(SCRIPT), "independently reviewed launcher bytes required"
    )
    commit = gate.get("implementation_git_sha")
    require(
        isinstance(commit, str) and len(commit) >= 7, "explicit committed implementation required"
    )
    for name in [m.SELF, m.CLI, m.TEST, completion.SELF, completion.TEST]:
        require(
            hashlib.sha256(git(root, "show", commit + ":" + name)).hexdigest()
            == admission["files"][name],
            "worktree/source Gate must match implementation commit: " + name,
        )
    require(
        gate["resources"] == m.resources() and gate["sampler_calls"] == 0,
        "fixed zero-call numerical resources required",
    )
    require(
        len(gate["parent_minimum_bytes"]) == 15
        and set(gate["external_reference_files"])
        == set(old.external_paths(root, original["freeze"])),
        "all15floors and exact outside11 closure required",
    )
    old.previous._require(admission["files"], gate["external_reference_files"])
    require(len(gate["external_reference_files"]) == 11, "exact eleven external references")
    return dict(
        old=old,
        m=m,
        completion=completion,
        admission=admission,
        head=git(root, "rev-parse", "HEAD").decode().strip(),
    )


def allowed_case(m):
    cfg = m.protocol()
    names = {
        "job.json",
        "inputs.json",
        "proposal.json",
        "runtime.json",
        "result.json",
        "stream-summary.json",
        "precision.json",
        "aggregate-diagnostics.json",
        "integration-start.json",
        "output-checksums.json",
    }
    names |= {
        f"blocks/df{df}-rep{r}-{first:06d}.json"
        for df in cfg["proposal_df"]
        for r in range(4)
        for first in range(0, max(cfg["levels"]), cfg["stream_block_size"])
    }
    return names


def locations(root, rt):
    m = rt["m"]
    control = root / Path(m.GATE).parent / "control"
    return control, control / "production-v1", root / m.CASE_OUTPUT


def stops(root, rt):
    control, _, _ = locations(root, rt)
    return [*rt["completion"].stop_paths(root), control / "STOP"]


def scan(root, rt):
    """Only predeclared current producer/control files may grow; other history stays closed."""
    old, m, c = rt["old"], rt["m"], rt["completion"]
    control, run, case = locations(root, rt)
    controls = {
        run / n
        for n in [
            "spec.json",
            "worker.log",
            "supervisor.json",
            "receipt.json",
            "failed-receipt.json",
            "failure.json",
        ]
    } | {control / ".controller.lock", control / "STOP"}
    producers = {case / n for n in allowed_case(m)}
    known = {root / p for p in rt["admission"]["files"]}
    for name in c.EXTRA_ROOTS:
        base = root / name
        if not base.exists() and not base.is_symlink():
            continue
        for p in [base, *base.rglob("*")]:
            require(
                p.resolve() == p and (p.is_file() or p.is_dir()), "literal regular numeric tree"
            )
            if p.is_dir():
                require(
                    any(p in q.parents for q in known | controls | producers),
                    "unlisted numerical directory",
                )
            else:
                require(p in known | controls | producers, "unlisted numerical file")
                require(p.stat().st_size <= old.r.FILE_MAX, "per-file cap")
                if p in known:
                    require(
                        sha(p) == rt["admission"]["files"][str(p.relative_to(root))],
                        "closed numerical history changed",
                    )
    require(
        not any(p.name.startswith("sampling-start") for p in case.rglob("*")),
        "numerical integration must never create sampling markers",
    )
    require(
        old.r.byte_count(case) + old.r.byte_count(run) <= old.r.MAX_JOB,
        "combined case/control32MiB cap",
    )


def state_sha(root, old):
    path = root / old.STATE
    return sha(path) if path.is_file() and path.resolve() == path else "missing_or_nonliteral"


def budget(root, rt):
    old, c, a = rt["old"], rt["completion"], rt["admission"]
    require(old.quota(root, a, reserve=True) is None, "old storage/cache/floor budget")
    parents = old.r.parent_roots(root)
    global_extra = old.r.byte_count(
        *c.outside_roots(root, old.previous.counted_roots(root, parents) + old.global_roots(root))
    )
    local_extra = old.r.byte_count(*c.outside_roots(root, old.roots(root)))
    external = sum((root / p).stat().st_size for p in a["gate"]["external_reference_files"])
    require(
        old.r.working_bytes(root, parents)
        + old.r.byte_count(*old.global_roots(root))
        + external
        + global_extra
        + old.r.RESERVE
        <= 3072 * old.r.MIB,
        "global3GiB/reserve608 budget",
    )
    require(
        old.r.byte_count(*old.roots(root)) + local_extra + old.r.RESERVE <= 2048 * old.r.MIB,
        "local2GiB/reserve608 budget",
    )
    scan(root, rt)
    require(
        state_sha(root, old) == a["gate"]["original_state_sha256"],
        "retained original state changed",
    )
    require(not any(p.exists() or p.is_symlink() for p in stops(root, rt)), "STOP")


def stable(root, rt):
    rt["old"].previous._unchanged(root, rt["admission"]["files"])
    require(
        git(root, "rev-parse", "HEAD").decode().strip() == rt["head"],
        "HEAD changed during one-shot run",
    )
    require(sha(SCRIPT) == rt["admission"]["gate"]["launcher_sha256"], "launcher bytes changed")
    budget(root, rt)


@contextmanager
def leases(root, rt):
    old = rt["old"]
    control, _, _ = locations(root, rt)
    with old.r._leases(root):
        stable(root, rt)
        control.mkdir(parents=True, exist_ok=True)
        lock = control / ".controller.lock"
        write(lock, {"pid": os.getpid(), "gate_sha256": rt["admission"]["files"][rt["m"].GATE]})
        try:
            yield {
                "path": str(lock.relative_to(root)),
                "sha256": sha(lock),
                "disposition": "released_exclusive_lease",
            }
        finally:
            lock.unlink()


def launch(root, rt):
    old, m, a = rt["old"], rt["m"], rt["admission"]
    control, run, case = locations(root, rt)
    require(
        not case.exists() and not case.is_symlink() and not run.exists() and not run.is_symlink(),
        "one new canonical execution only; no retry/resume",
    )
    stable(root, rt)
    try:
        with leases(root, rt) as released:
            stable(root, rt)
            run.mkdir()
            spec = run / "spec.json"
            log = run / "worker.log"
            supervisor = run / "supervisor.json"
            receipt = run / "receipt.json"
            write(spec, m.job_descriptor())
            before = state_sha(root, old)
            ended, failures = threading.Event(), []

            def watch():
                while not ended.wait(0.1):
                    try:
                        budget(root, rt)
                    except Exception as exc:
                        failures.append(str(exc))
                        try:
                            with (control / "STOP").open("x") as f:
                                f.write(str(exc))
                        except FileExistsError:
                            pass
                        return

            old.limit_worker_file_size(old.r.FILE_MAX)
            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            try:
                stable(root, rt)
                try:
                    process = old.supervise(
                        [
                            sys.executable,
                            str(root / m.CLI),
                            "--output",
                            str(case),
                            "--max-output-bytes",
                            str(old.r.FILE_MAX),
                        ],
                        log,
                        control / "STOP",
                        600,
                    )
                except BaseException as exc:
                    process = {
                        "returncode": 130 if isinstance(exc, KeyboardInterrupt) else None,
                        "reason": "interrupt"
                        if isinstance(exc, KeyboardInterrupt)
                        else "supervisor_failure",
                        "error": str(exc),
                    }
                write(
                    supervisor,
                    {
                        **process,
                        "sampler_calls": 0,
                        "sampler_markers": len(list(case.rglob("sampling-start*.json"))),
                        "integration_markers": int((case / "integration-start.json").is_file()),
                        "numeric_gate_sha256": a["files"][m.GATE],
                        "original_kernel_gate_sha256": a["files"][old.fit.GATE],
                        "specification_freeze_sha256": a["files"][old.fit.data.FREEZE],
                        "protocol_sha256": m.fingerprint(m.protocol()),
                        "job_sha256": sha(spec),
                        "invocation_git_sha": rt["head"],
                        "launcher_sha256": sha(SCRIPT),
                        "source_identity": m.fingerprint(a["files"]),
                        "original_state_before_sha256": before,
                        "original_state_after_sha256": state_sha(root, old),
                        "monitor_failures": list(failures),
                    },
                )
                stable(root, rt)
                require(
                    not failures
                    and process["reason"] == "worker_exit"
                    and process["returncode"] in [0, 2],
                    "supervised numerical computation failed",
                )
                candidate = m.candidate_artifacts(root, a["files"])
                require(
                    candidate.get("semantics_verified") is False
                    and candidate.get("sampler_calls") == 0,
                    "only unverified candidate byte proof is permitted",
                )
                stable(root, rt)
                write(
                    receipt,
                    {
                        "status": "unverified_candidate_requires_independent_cold_SCI",
                        "candidate": candidate,
                        "job": m.job_descriptor(),
                        "sampler_calls_charged": 0,
                        "sampler_calls_started": 0,
                        "source_gate": m.GATE,
                        "source_gate_sha256": a["files"][m.GATE],
                        "supervisor_sha256": sha(supervisor),
                        "original_state_before_sha256": before,
                        "original_state_after_sha256": state_sha(root, old),
                        "released_lease": released,
                        "numerical_result_is_not_scientifically_accepted": True,
                    },
                )
                stable(
                    root, rt
                )  # Includes final receipt bytes; late failure cannot leave a success receipt.
                require(not failures, "late monitor failure")
            except BaseException as exc:
                if receipt.exists():
                    receipt.rename(run / "failed-receipt.json")
                write(
                    run / "failure.json",
                    {
                        "status": "needs_review",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "sampler_calls_charged": 0,
                        "sampler_calls_started": 0,
                        "original_state_before_sha256": before,
                        "original_state_after_sha256": state_sha(root, old),
                    },
                )
                raise
            finally:
                ended.set()
                watcher.join(timeout=2)
        # Every shared and numeric lease has now exited successfully. Recheck the
        # formerly unguarded cleanup window before publishing a final return.
        stable(root, rt)
        released_paths = [
            control / ".controller.lock",
            root / old.r.OLD_OUTPUT / ".controller.lock",
            root / old.r.OUTPUT / ".controller.lock",
            root / old.CONTROL / ".controller.lock",
        ]
        require(
            all(not p.exists() and not p.is_symlink() for p in released_paths),
            "released lease path changed after cleanup",
        )
    except BaseException as exc:
        # A lease teardown error is also a failed launch, never a final success.
        final = run / "receipt.json"
        if final.exists():
            final.rename(run / "failed-receipt.json")
        failure = run / "failure.json"
        if run.exists() and not failure.exists():
            write(
                failure,
                {
                    "status": "needs_review",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "sampler_calls_charged": 0,
                    "sampler_calls_started": 0,
                    "original_state_after_sha256": state_sha(root, old),
                },
            )
        raise
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    rt = admit(root)
    if not args.execute:
        stable(root, rt)
        print(
            json.dumps(
                {
                    "status": "dry_metadata_admission_only",
                    "sampler_calls": 0,
                    "integration_started": False,
                }
            )
        )
        return
    print(str(launch(root, rt)))


if __name__ == "__main__":
    main()
