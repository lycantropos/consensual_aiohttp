import multiprocessing

MAX_RUNNING_NODES_COUNT = max(multiprocessing.cpu_count() - 1, 1)
