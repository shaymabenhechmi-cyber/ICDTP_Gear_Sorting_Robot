import argparse,sys
from top_view_pipeline import run_top_view
from side_view_pipeline import run_side_view

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",choices=["top","side"])
    args = parser.parse_args()

    while True:

        if args.mode is None:
            c = input("1: Top | 2: Side | q: Quit : ")
        else:
            c = args.mode

        if c=="1" or c=="top":
            run_top_view()

        elif c=="2" or c=="side":
            run_side_view()

        elif c=="q":
            sys.exit()

if __name__=="__main__":
    main()