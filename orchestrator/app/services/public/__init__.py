"""Business-logic services for public API routers.

One service per surface (pairing, sync, handoff, k8s remote, marketplace
install). Keep routers thin — they should delegate to these modules.
"""
