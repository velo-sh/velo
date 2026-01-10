import signal
import os
import sys


def check():
    with open("/tmp/probe.debug", "w") as debug_f:
        debug_f.write("Probe Start\n")
        try:
            sigterm = signal.getsignal(signal.SIGTERM)
            sigpipe = signal.getsignal(signal.SIGPIPE)
            debug_f.write(f"Signals: {sigterm}, {sigpipe}\n")

            try:
                mask = signal.pthread_sigmask(signal.SIG_BLOCK, [])
                mask_empty = len(mask) == 0
            except:
                mask_empty = True
            debug_f.write(f"Mask empty: {mask_empty}\n")

            with open("/tmp/signal_results.txt", "w") as f:
                f.write("SIGTERM_DFL:" + str(sigterm == signal.SIG_DFL) + "\n")
                f.write("SIGPIPE_DFL:" + str(sigpipe == signal.SIG_DFL) + "\n")
                f.write("MASK_EMPTY:" + str(mask_empty) + "\n")
            debug_f.write("Results written\n")
            sys.exit(0)
        except Exception as e:
            debug_f.write(f"ERROR: {str(e)}\n")
            import traceback

            traceback.print_exc(file=debug_f)
            sys.exit(1)


if __name__ == "__main__":
    check()
