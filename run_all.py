"""One command: generate demo data -> analyse -> start the web map.

    python run_all.py              # full run, then opens the server
    python run_all.py --no-server  # data + analysis only
"""
import argparse

import analyze
import generate_data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-server", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    print("== 1/3 Generating synthetic city ==")
    generate_data.generate(a.seed)
    print("\n== 2/3 Running solar + equity analysis ==")
    analyze.run()
    if a.no_server:
        print("\nDone. Start the map with:  python app.py")
        return
    print("\n== 3/3 Starting web map ==")
    import app
    app.load()
    print("Open http://127.0.0.1:5000")
    app.app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
