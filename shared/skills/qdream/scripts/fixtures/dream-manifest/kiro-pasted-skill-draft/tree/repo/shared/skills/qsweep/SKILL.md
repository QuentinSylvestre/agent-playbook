---
name: qsweep
description: "Second synthetic fixture skill with a bare arguments line"
---

# Sweep Fixture

The sweep fixture reads the mode argument on the next line and nothing else.
$ARGUMENTS
The mode argument selects between the light pass and the full pass of the fixture.
In the light pass the fixture only counts the entries and prints the total count.
In the full pass the fixture also re-reads every entry and checks its anchor again.
