# Ideas & Program Synthesis

> Idea generation, program synthesis, and finalize flow.

## Overview

The improvement loop has three AI-driven phases: **idea generation**, **program synthesis**, and **finalization**.

## Ideas (`ideas.py`)

- `read_ideas()` — Load previously generated ideas
- `append_idea()` — Record a new idea to the ideas log
- Ideas are tracked to avoid repeating failed strategies and to inform escalation

## Program (`program.py`)

- `generate_program()` — Synthesize a concrete code change plan from an idea
- The program is a structured set of edits to apply to mutable files

## Finalize (`finalize.py`)

- Post-experiment cleanup and result formatting
- Handles the transition from experiment completion to result recording
