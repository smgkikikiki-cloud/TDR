"""TDR Identity Bootstrap -- contract-only package (milestone 1).

Decides whether an external vehicle identity that Identity Resolution could not map to any existing TDR canonical
vehicle may become a minimal canonical identity (a ``DISCOVERED`` shell), and describes the write plan and the
``VEHICLE_IDENTITY_CREATED`` hand-off event. There is no engine, no persistence and no database access here; see README.md.
"""
