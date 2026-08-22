## Purpose

Any agent, on entry (new session, takeover, handoff), first does a "handshake": **read existing docs in a fixed order → extract key points → echo back understanding**, then start work. The goal is auditable handoff and avoiding the drift/misunderstanding caused by "acting without reading". This is the executable form of the Session startup check.

