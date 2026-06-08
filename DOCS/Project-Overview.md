# Voice Interview Assistant — Project Overview

> Upload your resume → get interviewed by a voice AI → receive a scored PDF report with specific, actionable feedback.

---

## Table of Contents

1. [What We're Building](#1-what-were-building)
2. [Scope](#2-scope)
3. [Core User Flow](#3-core-user-flow)
4. [Layers](#4-layers)
5. [Success Criteria](#5-success-criteria)

---

## 1. What We're Building

A voice-based mock interview assistant that reads a candidate's resume, conducts a personalized interview, and produces a scored PDF report with feedback anchored to their exact words.

The gap detection feature is the core differentiator. The system identifies weak spots on the resume — short tenures, missing metrics, vague skill claims — and generates questions that probe exactly those gaps. No other open-source tool does this.

| Feature | Generic tools | This project |
|---|---|---|
| Questions grounded in your resume | Rarely | Always |
| Gap-probing (weak spots on resume) | Never | Core feature |
| Adaptive follow-ups | No | Yes |
| Report references your actual words | No | Direct quotes |
| Score breakdown by dimension | No | 5-axis scoring |
| Rewrite suggestions | Generic | Personalized |
| Voice-based | Rarely | Full voice loop |

---

## 2. Scope

### In scope

- PDF resume upload and structured parsing with gap analysis
- Personalized 28-question bank generated before the interview starts
- Real-time voice interview: agent speaks, listens, follows up adaptively
- Per-answer scoring on 5 dimensions, running silently in the background
- PDF report with per-answer feedback, exact transcript quotes, and rewrite suggestions
- Session history so users can track score improvement across multiple runs
- Job description targeting: tailor questions to a specific role if a JD is provided

### Out of scope

- Multi-user accounts or authentication
- Video recording or camera input
- Integration with job platforms (LinkedIn, Greenhouse, etc.)
- Automated scheduling or calendar features
- Mobile app — browser-based only

---

## 3. Core User Flow

1. **Upload** — User lands on the page and uploads their PDF resume. Optionally pastes a job description to target a specific role.
2. **Parse** — The system extracts structured data from the resume: work history, skills, education, and detected gaps.
3. **Generate** — A personalized 28-question bank is prepared before the interview begins. Questions are grounded in the resume and target its weak spots.
4. **Interview** — User clicks Start. The agent speaks questions aloud. The user answers by speaking. The agent decides whether to follow up, probe deeper, or move on based on the answer.
5. **Score** — Each answer is scored silently in the background while the conversation continues. The user never notices.
6. **Report** — After the session ends, the system synthesizes all scores into a PDF report. The user downloads it.

---

## 4. Layers

### Layer 1 — Resume Parser

Takes the uploaded PDF and produces a structured JSON object that every downstream layer uses. Raw PDF text is never read again after this step.

Extracts: name, contact info, skills by category, work experience with dates, and education. For each experience entry it flags whether metrics are present and which bullets are vague.

The most important output is the `gap_analysis` field — a list of specific observations about weak spots on the resume. Examples: short tenure at a company with no explanation, skills claimed but no supporting project, employment gaps, or experience bullets with no quantifiable outcome. These observations directly drive the gap-probing questions in the next layer.

### Layer 2 — Question Bank Generator

Takes the structured resume JSON and produces 28 personalized questions before the session starts. Questions are not generated in real time during the call — the full bank is ready before the interview begins.

Five categories:
- **Behavioral (10)** — Each question references a specific bullet from the resume. The user is asked to walk through what they did, what the outcome was, and their role in it.
- **Technical (8)** — Depth checks on skills and tools listed on the resume. The question targets exactly what they claimed to know.
- **Gap-probing (5)** — Each question targets one item from `gap_analysis`. Framed as curious rather than confrontational, but the answer will reveal the gap either way.
- **Situational (3)** — Role-specific hypotheticals testing judgment in realistic scenarios.
- **Closing (2)** — What they're looking for next; self-assessment of their weakest area.

Each question also carries a prepared follow-up for vague answers and a prepared follow-up for strong answers, so the agent can respond appropriately to either.

### Layer 3 — Voice Interview Loop

Runs the live interview. The agent speaks a question, listens to the user's answer, and decides what to do next.

Decision logic: if the answer is short or vague, the agent uses the prepared vague follow-up. If the answer is strong, the agent probes deeper with the prepared strong follow-up. If the answer is complete, the agent moves on. Each question allows a maximum of two follow-ups before moving on regardless.

Edge cases handled: user asks to repeat the question, user goes silent for more than 8 seconds, user asks to skip, user interrupts while the agent is speaking, session exceeds 30 minutes.

The full transcript — question, answer, and any follow-ups — is stored per question in the database.

### Layer 4 — Silent Per-Answer Scoring

After each answer is stored, a scoring pass runs asynchronously in the background. It completes without adding any latency to the voice conversation.

Five scoring dimensions (1–5 scale each):
- **Specificity** — Did they give a concrete example with real details?
- **Outcome** — Did they state a measurable result?
- **Relevance** — Did they actually answer what was asked?
- **Clarity** — Was the answer coherent and easy to follow?
- **Confidence** — Were there minimal filler words and appropriate answer length?

Each scored answer also captures the strongest moment, the weakest moment, and a suggested rewrite. Scores are never collapsed to a single number during this layer — aggregation happens in the report.

### Layer 5 — Report Generator

After the session ends, synthesizes all per-answer scores into a structured report and renders it as a downloadable PDF.

Report contents:
- Overall score and per-dimension breakdown with score bars
- Top moments: best answer, weakest answer, and missed opportunity
- Per-question feedback using exact transcript quotes — every feedback item shows what the user said, why it was weak, and a rewritten version in first person
- Five prioritized action items, each referencing something specific said during the interview

The report is the artifact users share. It needs to look professional and read as a direct reflection of their specific session, not a generic rubric.

---

## 5. Success Criteria

**Resume parser**
Any PDF uploaded produces a valid structured JSON with gap_analysis populated in under 10 seconds. Reading the gap_analysis out loud should sound like observations a real recruiter would make.

**Question bank**
28 questions generated in under 15 seconds. Every behavioral question references a specific resume bullet. Every gap-probing question targets a real item from gap_analysis. No question should feel like it could have been written without reading the resume.

**Voice interview**
A complete 5-minute session runs end-to-end with natural transitions. The agent follows up organically at least 3 times in a 10-question session based on actual answer quality. The user does not notice scoring happening in the background.

**Report**
Every action item in the report references something the user specifically said — not generic advice. The PDF is professional enough to screenshot and share. A stranger reading the report should be able to identify exactly which answers were strong and which were weak.

**End-to-end**
Upload resume → complete voice session → download PDF. Full flow works without errors. Anyone cloning the repo can run the demo in under 10 minutes.
