# Channel adapters

`app.py` is the reference Web and OneBot webhook adapter. A production NapCat
adapter should translate OneBot events into `InteractionEnvelope` and send only
the `ResponseEnvelope` content/media back to QQ. It must not access personal
memory or secretary storage directly.

`legacy_adapter.py` provides an optional bridge to the original project through
`LEGACY_AGENT_ROOT`; the original source tree remains untouched.
