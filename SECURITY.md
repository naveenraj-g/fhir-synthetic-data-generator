# Security

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's private reporting instead:
**Security tab > Report a vulnerability** on this repository. Include what you found, how to reproduce it and what it
affects. You will get a reply as soon as the maintainer can; this is a small project, so please be patient.

## What this project does and does not protect

* The data it produces is **synthetic** (every resource is tagged `HTEST`). It is for testing, demos and development.
  Do not treat it as real patient data, and do not mix it into real clinical systems.
* The app has **no login**. Anyone who can reach its port can generate data and see every job. Run it on your own
  machine or a trusted network, or put an authenticating reverse proxy in front before exposing it.
* Callers cannot reach file paths, Docker images or JVM flags: a request may only set a small allow-list of Synthea
  properties. If you find a way around that, it is a vulnerability: please report it.
