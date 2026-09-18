import boto3
import numpy as np


# ============================================================
# R2 CONFIGURATION
# ============================================================

R2_ACCESS_KEY_ID = "00e18b0c16ecb3395cd6f7c8e0eb3554"
R2_SECRET_ACCESS_KEY = "33799355abaedc234309dbfbc80a2a66c3bfd856f0dcaecf0031e1fbcbcd84a0"
R2_ENDPOINT_URL = "https://98f8e959e677f16bddcf44f609fec6a0.r2.cloudflarestorage.com"

R2_BUCKET_NAME = "stocks-data"





# ============================================================
# R2 CLIENT
# ============================================================

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
)


# ============================================================
# SETTINGS
# ============================================================

NUMBER_OF_BINS = 20

# Maximum-sized stock takes 1000 / 60 minutes.
MAX_STOCK_TIME_MINUTES = 1000


# ============================================================
# GET ROOT-LEVEL FILES
# ============================================================

def get_root_files():

    paginator = s3.get_paginator("list_objects_v2")

    files = []

    for page in paginator.paginate(
        Bucket=R2_BUCKET_NAME
    ):

        for obj in page.get("Contents", []):

            key = obj["Key"]

            # Only include files directly in the bucket.
            # Anything containing "/" is inside a folder.
            if "/" not in key:

                files.append({
                    "key": key,
                    "size": obj["Size"],
                })

    return files


# ============================================================
# FORMAT TIME
# ============================================================

def format_time(minutes):

    hours = minutes / 60
    days = hours / 24

    return (
        f"{minutes:,.2f} min | "
        f"{hours:,.2f} hours | "
        f"{days:,.2f} days"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 80)
    print("R2 ROOT-LEVEL FILE SIZE ANALYSIS")
    print("=" * 80)

    files = get_root_files()

    if not files:

        print("No root-level files found.")
        return

    print(
        f"Files found: {len(files):,}"
    )

    # ========================================================
    # FILE SIZE STATISTICS
    # ========================================================

    sizes = np.array(
        [file["size"] for file in files],
        dtype=float,
    )

    minimum_size = sizes.min()
    maximum_size = sizes.max()
    average_size = sizes.mean()
    median_size = np.median(sizes)

    print()
    print("FILE SIZE STATISTICS")
    print("-" * 80)

    print(
        f"Minimum: {minimum_size / (1024 ** 3):,.3f} GB"
    )

    print(
        f"Average: {average_size / (1024 ** 3):,.3f} GB"
    )

    print(
        f"Median:  {median_size / (1024 ** 3):,.3f} GB"
    )

    print(
        f"Maximum: {maximum_size / (1024 ** 3):,.3f} GB"
    )

    # ========================================================
    # ESTIMATED TIME
    # ========================================================

    print()
    print("TIME ASSUMPTION")
    print("-" * 80)

    print(
        f"Maximum file: "
        f"{MAX_STOCK_TIME_MINUTES:.2f} minutes"
    )

    print(
        "Estimated time is proportional to file size."
    )

    # ========================================================
    # INDIVIDUAL STOCK ESTIMATES
    # ========================================================

    total_estimated_minutes = 0

    for file in files:

        size = file["size"]

        estimated_minutes = (
            size / maximum_size
        ) * MAX_STOCK_TIME_MINUTES

        file["estimated_minutes"] = (
            estimated_minutes
        )

        total_estimated_minutes += (
            estimated_minutes
        )

    # ========================================================
    # 20 BINS FROM MIN TO MAX
    # ========================================================

    bin_edges = np.linspace(
        minimum_size,
        maximum_size,
        NUMBER_OF_BINS + 1,
    )

    bins = []

    for i in range(NUMBER_OF_BINS):

        lower = bin_edges[i]
        upper = bin_edges[i + 1]

        bins.append({
            "number": i + 1,
            "lower": lower,
            "upper": upper,
            "files": [],
            "total_minutes": 0,
        })

    # ========================================================
    # ASSIGN FILES TO BINS
    # ========================================================

    for file in files:

        size = file["size"]

        # Make sure the maximum value enters
        # the final bin.
        if size == maximum_size:

            bin_index = NUMBER_OF_BINS - 1

        else:

            bin_index = int(
                (
                    (size - minimum_size)
                    /
                    (maximum_size - minimum_size)
                )
                * NUMBER_OF_BINS
            )

            bin_index = max(
                0,
                min(
                    bin_index,
                    NUMBER_OF_BINS - 1,
                ),
            )

        bins[bin_index]["files"].append(
            file
        )

        bins[bin_index]["total_minutes"] += (
            file["estimated_minutes"]
        )

    # ========================================================
    # PRINT BIN SUMMARY
    # ========================================================

    print()
    print("=" * 100)
    print("20-BIN FILE SIZE / TIME ANALYSIS")
    print("=" * 100)

    for bin_data in bins:

        lower_gb = (
            bin_data["lower"]
            / (1024 ** 3)
        )

        upper_gb = (
            bin_data["upper"]
            / (1024 ** 3)
        )

        stock_count = len(
            bin_data["files"]
        )

        total_minutes = (
            bin_data["total_minutes"]
        )

        print()
        print(
            f"BIN {bin_data['number']:02d}"
        )

        print(
            f"Size range: "
            f"{lower_gb:,.3f} GB - "
            f"{upper_gb:,.3f} GB"
        )

        print(
            f"Stocks: {stock_count:,}"
        )

        print(
            f"Estimated time: "
            f"{format_time(total_minutes)}"
        )

        # ----------------------------------------------------
        # Individual stocks in this bin
        # ----------------------------------------------------

        if stock_count > 0:

            print(
                "Stocks:"
            )

            for file in sorted(
                bin_data["files"],
                key=lambda x: x["size"],
            ):

                size_gb = (
                    file["size"]
                    / (1024 ** 3)
                )

                print(
                    f"    "
                    f"{file['key']:<15} "
                    f"{size_gb:>10,.3f} GB | "
                    f"{file['estimated_minutes']:>8,.2f} min"
                )


    # ========================================================
    # OVERALL ESTIMATE
    # ========================================================

    print()
    print("=" * 100)
    print("OVERALL ESTIMATED TIME")
    print("=" * 100)

    print(
        f"Total stocks: "
        f"{len(files):,}"
    )

    print(
        f"Total estimated time: "
        f"{format_time(total_estimated_minutes)}"
    )

    print(
        f"Average estimated time per stock: "
        f"{total_estimated_minutes / len(files):,.2f} minutes"
    )

    # ========================================================
    # FAST SUMMARY
    # ========================================================

    print()
    print("=" * 100)
    print("BIN SUMMARY")
    print("=" * 100)

    print(
        f"{'BIN':<6}"
        f"{'SIZE RANGE (GB)':<30}"
        f"{'STOCKS':>10}"
        f"{'TIME (MIN)':>18}"
        f"{'TIME (HOURS)':>18}"
    )

    print("-" * 100)

    for bin_data in bins:

        lower_gb = (
            bin_data["lower"]
            / (1024 ** 3)
        )

        upper_gb = (
            bin_data["upper"]
            / (1024 ** 3)
        )

        stock_count = len(
            bin_data["files"]
        )

        total_minutes = (
            bin_data["total_minutes"]
        )

        print(
            f"{bin_data['number']:<6}"
            f"{lower_gb:,.3f} - {upper_gb:,.3f}"
            f"{'':<10}"
            f"{stock_count:>10,}"
            f"{total_minutes:>18,.2f}"
            f"{total_minutes / 60:>18,.2f}"
        )

    print()
    print("=" * 100)
    print("DONE")
    print("=" * 100)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()