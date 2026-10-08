"""The node agent: the only process that sends to its node's runtime.

One per runtime host, colocated with the runtime (final spec on #24, §1). It
owns dispatch, the node-wide block on uncertain outcomes, and the evidence that
clears it. The gateway and the admin entrances reach the runtime only through
it once `NODE_AGENT_ENABLED` is on, which waits for PR4b's all-senders audit.

The process never forks (design revision 4): its host lock is held by an open
file description that a forked child would share and keep alive. A test walks
this package and refuses `os.fork`, `subprocess` and `multiprocessing`.
"""
