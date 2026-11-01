---
name: qfixture
description: "Synthetic fixture skill used only by dream-manifest self-tests"
argument-hint: "<scope>"
---

# Fixture Skill

## Your role

You are the fixture skill and you exist only so the stripping self-test has a body to find.
Read every file the caller names before proposing any change to the fixture module.
Never write outside the scratch directory that the caller passes in the brief.
Report findings as a numbered list, one finding per line, most severe first.

Arguments: $ARGUMENTS

## Process

1. Confirm the scope argument names a directory that exists in the working tree.
2. Walk the directory and list every file whose name ends in the fixture suffix.
3. Summarize the list for the caller and stop without editing anything at all.
