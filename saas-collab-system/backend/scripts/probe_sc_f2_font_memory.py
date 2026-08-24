import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time


def current_rss_kib(pid=None):
    target = pathlib.Path("/proc") / str(pid or os.getpid()) / "status"
    for line in target.read_text(encoding="ascii").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise RuntimeError(f"VmRSS is unavailable for pid {pid or os.getpid()}.")


def max_rss_kib():
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def load_inputs(bundle_dir, corpus_path):
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    return manifest, corpus


def register_fonts(bundle_dir, manifest):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = []
    for asset in manifest["assets"]:
        name = asset["postscript_name"]
        pdfmetrics.registerFont(TTFont(name, bundle_dir / asset["path"]))
        fonts.append((name, asset["role"]))
    return fonts


def render_pdf(output, fonts, corpus):
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(
        str(output),
        pagesize=(595.2756, 841.8898),
        invariant=1,
        pageCompression=1,
    )
    pdf.setCreator("SC-F2 font memory probe")
    for font_name, role in fonts:
        pdf.setFont(font_name, 11)
        y = 800
        for sample in corpus["positive_samples"]:
            pdf.drawString(36, y, f"{role}:{sample['id']}: {sample['text']}")
            y -= 28
        pdf.showPage()
    pdf.save()
    payload = output.read_bytes()
    return {
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def worker(args):
    args.work_dir.mkdir(parents=True, exist_ok=True)
    baseline_rss = current_rss_kib()
    started = time.perf_counter()
    manifest, corpus = load_inputs(args.bundle_dir, args.corpus)
    fonts = register_fonts(args.bundle_dir, manifest)
    registered_rss = current_rss_kib()
    first_pdf = render_pdf(args.work_dir / "first.pdf", fonts, corpus)
    first_rss = current_rss_kib()
    first_peak = max_rss_kib()

    for index in range(args.steady_renders):
        render_pdf(args.work_dir / f"steady-{index}.pdf", fonts, corpus)
    steady_rss = current_rss_kib()
    steady_peak = max_rss_kib()
    result = {
        "baseline_rss_kib": baseline_rss,
        "registered_rss_kib": registered_rss,
        "first_render_current_rss_kib": first_rss,
        "first_render_peak_rss_kib": first_peak,
        "first_render_pdf": first_pdf,
        "steady_renders": args.steady_renders,
        "steady_current_rss_kib": steady_rss,
        "steady_peak_rss_kib": steady_peak,
        "steady_current_growth_from_first_kib": max(0, steady_rss - first_rss),
        "steady_peak_growth_from_first_kib": max(0, steady_peak - first_peak),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    args.result_file.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    if args.ready_file:
        args.ready_file.write_text("ready\n", encoding="ascii")
        deadline = time.monotonic() + args.timeout_seconds
        while not args.release_file.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("Concurrent memory probe release timed out.")
            time.sleep(0.02)
    return result


def run_worker_process(script, common, work_dir, result_file, ready=None, release=None):
    command = [
        sys.executable,
        str(script),
        "--worker",
        "--bundle-dir",
        str(common.bundle_dir),
        "--corpus",
        str(common.corpus),
        "--work-dir",
        str(work_dir),
        "--result-file",
        str(result_file),
        "--steady-renders",
        str(common.steady_renders),
        "--timeout-seconds",
        str(common.timeout_seconds),
    ]
    if ready and release:
        command.extend(["--ready-file", str(ready), "--release-file", str(release)])
    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_for_ready(processes, ready_files, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    while not all(path.exists() for path in ready_files):
        for process in processes:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise RuntimeError(
                    f"Concurrent worker exited early ({process.returncode}): "
                    f"{stdout}\n{stderr}"
                )
        if time.monotonic() >= deadline:
            raise TimeoutError("Concurrent workers did not become ready.")
        time.sleep(0.02)


def read_result(path):
    return json.loads(path.read_text(encoding="utf-8"))


def controller(args):
    if not pathlib.Path("/proc/self/status").is_file():
        raise RuntimeError("The authoritative memory probe requires Linux /proc.")
    script = pathlib.Path(__file__).resolve()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    single_result = args.work_dir / "single-result.json"
    single = run_worker_process(
        script,
        args,
        args.work_dir / "single",
        single_result,
    )
    stdout, stderr = single.communicate(timeout=args.timeout_seconds)
    if single.returncode:
        raise RuntimeError(f"Single memory worker failed: {stdout}\n{stderr}")
    first_steady = read_result(single_result)

    processes = []
    ready_files = []
    release_files = []
    result_files = []
    for index in range(args.concurrency):
        worker_dir = args.work_dir / f"concurrent-{index}"
        ready = worker_dir / "ready"
        release = worker_dir / "release"
        result = worker_dir / "result.json"
        worker_dir.mkdir(parents=True, exist_ok=True)
        processes.append(
            run_worker_process(script, args, worker_dir, result, ready, release)
        )
        ready_files.append(ready)
        release_files.append(release)
        result_files.append(result)

    wait_for_ready(processes, ready_files, args.timeout_seconds)
    worker_current = [current_rss_kib(process.pid) for process in processes]
    aggregate_worker_rss = sum(worker_current)
    controller_rss = current_rss_kib()
    aggregate_with_controller = aggregate_worker_rss + controller_rss
    for release in release_files:
        release.write_text("release\n", encoding="ascii")

    concurrent_results = []
    for process, result_file in zip(processes, result_files):
        stdout, stderr = process.communicate(timeout=args.timeout_seconds)
        if process.returncode:
            raise RuntimeError(f"Concurrent memory worker failed: {stdout}\n{stderr}")
        concurrent_results.append(read_result(result_file))

    violations = []
    if first_steady["first_render_peak_rss_kib"] > args.first_max_rss_kib:
        violations.append("first_render_peak_rss")
    if (
        first_steady["steady_current_growth_from_first_kib"]
        > args.steady_growth_max_kib
    ):
        violations.append("steady_current_growth")
    if max(worker_current) > args.concurrent_worker_max_rss_kib:
        violations.append("concurrent_worker_current_rss")
    if aggregate_worker_rss > args.concurrent_aggregate_max_rss_kib:
        violations.append("concurrent_aggregate_worker_rss")
    if aggregate_with_controller > args.concurrent_total_max_rss_kib:
        violations.append("concurrent_total_rss")

    result = {
        "schema_version": "sc-f2-label-font-memory-probe-v1",
        "result": "PASS" if not violations else "FAIL",
        "metric_contract": {
            "first": "fresh subprocess peak RSS after font registration and first PDF",
            "steady": "current RSS growth after repeated PDFs in the same subprocess",
            "concurrent": "simultaneous current RSS after each isolated worker rendered and held",
        },
        "budgets": {
            "first_render_peak_rss_max_kib": args.first_max_rss_kib,
            "steady_current_growth_max_kib": args.steady_growth_max_kib,
            "concurrent_workers": args.concurrency,
            "concurrent_worker_current_rss_max_kib": args.concurrent_worker_max_rss_kib,
            "concurrent_aggregate_worker_rss_max_kib": (
                args.concurrent_aggregate_max_rss_kib
            ),
            "concurrent_total_rss_max_kib": args.concurrent_total_max_rss_kib,
        },
        "first_and_steady": first_steady,
        "concurrent": {
            "workers": args.concurrency,
            "worker_current_rss_kib": worker_current,
            "aggregate_worker_rss_kib": aggregate_worker_rss,
            "controller_rss_kib": controller_rss,
            "aggregate_with_controller_rss_kib": aggregate_with_controller,
            "worker_results": concurrent_results,
        },
        "violations": violations,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if violations:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True, type=pathlib.Path)
    parser.add_argument("--corpus", required=True, type=pathlib.Path)
    parser.add_argument("--work-dir", required=True, type=pathlib.Path)
    parser.add_argument("--steady-renders", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--first-max-rss-kib", type=int, default=131072)
    parser.add_argument("--steady-growth-max-kib", type=int, default=16384)
    parser.add_argument("--concurrent-worker-max-rss-kib", type=int, default=131072)
    parser.add_argument(
        "--concurrent-aggregate-max-rss-kib", type=int, default=229376
    )
    parser.add_argument("--concurrent-total-max-rss-kib", type=int, default=245760)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--result-file", type=pathlib.Path)
    parser.add_argument("--ready-file", type=pathlib.Path)
    parser.add_argument("--release-file", type=pathlib.Path)
    args = parser.parse_args()

    if args.steady_renders < 1 or args.steady_renders > 50:
        raise ValueError("--steady-renders must be between 1 and 50.")
    if args.concurrency < 1 or args.concurrency > 4:
        raise ValueError("--concurrency must be between 1 and 4.")
    if args.worker:
        if not args.result_file:
            raise ValueError("--result-file is required in worker mode.")
        worker(args)
    else:
        controller(args)


if __name__ == "__main__":
    main()
