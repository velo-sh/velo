def compute_hio_score(baseline_samples, velo_samples, pss_reduction_pct=0.0):
    """
    Compute HIO Score (0-100)
    Formula: Score = (Time_Score * 0.7) + (Memory_Score * 0.3)
    """
    import statistics

    b_median = statistics.median(baseline_samples)
    v_median = statistics.median(velo_samples)

    # Time Speedup Score (0-100)
    speedup = b_median / max(v_median, 0.1)
    time_score = min(100, (90 if v_median < 50 else 50) + min(10, speedup / 2.0))

    # Memory Optimization Score (0-100)
    # Assume 80% PSS reduction is full score 100
    mem_score = min(100, (pss_reduction_pct / 0.8) * 100)

    final_score = (time_score * 0.7) + (mem_score * 0.3)
    return round(final_score, 1)


def print_hio_header(project_id, slogan):
    print("\033[38;5;33m" + "=" * 50 + "\033[0m")
    print(f" HIO PROJECT: {project_id}")
    print(f" SLOGAN: {slogan}")
    print("\033[38;5;33m" + "=" * 50 + "\033[0m")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=float, nargs="+", default=[500] * 10)
    parser.add_argument("--velo", type=float, nargs="+", default=[10] * 10)
    parser.add_argument("--mem-reduction", type=float, default=0.8)
    parser.add_argument("--project", type=str, default="HIO-GENERIC")
    parser.add_argument("--slogan", type=str, default="Wait less, build more.")
    args = parser.parse_args()

    score = compute_hio_score(args.baseline, args.velo, args.mem_reduction)
    print_hio_header(args.project, args.slogan)
    print(f">> HIO Score: {score} [Calculated with {args.mem_reduction * 100}% Memory Saving]")
