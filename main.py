import argparse, sys
from top_view_pipeline import run_top_view
from side_view_pipeline import run_side_view


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["top", "side"])
    args = parser.parse_args()

    while True:

        if args.mode is None:
            c = input("1: Top | 2: Side | q: Quit : ").strip().lower()
        else:
            c = args.mode

        if c in ["1", "top"]:
            run_top_view()

        elif c in ["2", "side"]:
            run_side_view()

        elif c == "q":
            print("Exiting...")
            break

        # si mode CLI direct → stop après exécution
        if args.mode is not None:
            break


if __name__ == "__main__":
    main()