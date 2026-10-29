"""Agent roles and task wording, separate from CrewAI orchestration."""

ROLES = {
    "requirements": (
        "Requirements analyst",
        "Define scope, measurable acceptance criteria, constraints and unresolved questions.",
    ),
    "design": (
        "Software architect",
        "Design interfaces, data flow, architecture and explicit tradeoffs for the agreed requirements.",
    ),
    "plan": (
        "Engineering planner",
        "Produce ordered implementation tasks and an independent verification plan.",
    ),
    "implement": (
        "Software engineer",
        "Implement the plan in the workspace; address concrete failures from previous verification attempts.",
    ),
    "review": (
        "Change reviewer",
        "Review actual source against requirements and verification evidence; identify gaps and risks.",
    ),
    "retrospective": (
        "Delivery analyst",
        (
            "Summarize observed outcomes, unresolved risks and actionable follow-up work "
            "without inventing telemetry."
        ),
    ),
}


DOCUMENT_INSTRUCTIONS = {
    "requirements": (
        "Write a requirements DOCUMENT describing intended future behavior. Include "
        "objective, scope, individually testable acceptance criteria, constraints, "
        "and genuinely unresolved questions. Treat the original task as the scope "
        "boundary: preserve every explicit criterion without adding features or "
        "tightening unspecified behavior. For example, a nonempty error string does "
        "not require prescribed wording. Concurrency, audit logging, performance "
        "targets and other optional capabilities are not requirements unless requested "
        "or necessary to satisfy an explicit criterion. Open questions must identify "
        "a decision that actually prevents fulfilling the requested behavior, explain "
        "which criterion it affects and why existing context cannot resolve it. An "
        "empty open_questions list is valid. Keep optional follow-ups outside the "
        "acceptance criteria and blocking questions. On revision, resolve in-scope "
        "findings; explicitly explain why an out-of-scope suggestion is excluded "
        "rather than adopting it as a new requirement."
    ),
    "design": (
        "Write the concrete DESIGN now. Choose an implementation approach appropriate"
        " to the task size. Specify interfaces to preserve or change, ordered data "
        "flow, algorithm decisions and alternatives with tradeoffs, edge cases and "
        "their handling, and a verification strategy. Resolve questions already "
        "answered by accepted requirements or repository documentation. Do not merely"
        " say to develop a design or list bugs; make the technical decisions without "
        "changing source."
    ),
    "plan": (
        "Write an executable PLAN now based on the accepted design. Provide ordered "
        "steps with a concrete action, file/component target, and completion "
        "criterion for each. Include verification steps and risks with mitigations. "
        "Separate implementation work from external verification and gated delivery. "
        "Do not change source or claim steps have executed."
    ),
}


def specialist_instructions(stage, document_type, revision):
    instruction = DOCUMENT_INSTRUCTIONS.get(
        stage,
        "Produce the complete deliverable for this stage, not a promise to do it later.",
    )
    if stage in {"review", "retrospective"}:
        instruction += (
            " The task and README describe the ORIGINAL defect before implementation. "
            "Assess current_changed_source, which contains the actual current file text, "
            "and completed verification results. Do not report the original defect as "
            "still present unless you can cite the exact current expression that causes "
            "it. Explicitly distinguish the original behavior from the repaired behavior."
        )
    if stage == "implement":
        instruction += (
            " Your deliverable is working source in the workspace. You must actually use "
            "write_source_file when the requested change is missing. A bug report, "
            "proposed patch, or advice to implement later is not a completed "
            "implementation. An empty workspace is valid: create the project structure, "
            "modules, tests, configuration and documentation required by the task. "
            "Do not wait for starter files. Read files only after listing confirms they exist."
        )
        instruction += (
            " First call check_current_candidate to obtain CURRENT failures and policy "
            "details. Inspect the current source. During repairs, prioritize these "
            "concrete failures over earlier design suggestions. Preserve working "
            "corrections. A prior design choice is not permission to violate project "
            "policy. After source edits, call check_current_candidate again and address "
            "remaining failures before finishing. Do not package or deploy. If the "
            "current candidate already passes both checks, preserve its working behavior "
            "instead of reimplementing the old design. Passing checks do not waive "
            "explicit deliverables they do not measure, such as requested regression "
            "tests. Inspect those deliverables and use write_source_file to complete "
            "any that are still missing. Never claim a file changed without writing it."
        )
        instruction += (
            " Implement the general rule from the requirements, not a list of specific "
            "failing test values. For character-category validation, express membership "
            "in the complete allowed category (using a suitable standard-library "
            "definition or exact range predicate). Test examples are evidence, not the "
            "exhaustive input domain."
        )
    if document_type:
        instruction += (
            " Existing bugs explain why the task exists. An unfixed implementation is "
            "expected at this stage; produce the document instead of a bug report or "
            "implementation audit. Keep the document proportional to the requested "
            "change."
        )
        instruction += (
            " Make concrete decisions, including the exact existing API or algorithm to "
            "use and expected behavior for each edge case. Preserve each acceptance "
            "criterion independently; do not conflate empty input with nonempty "
            "whitespace input. Do not introduce new performance or error-handling "
            "requirements. Questions already answered by the task are resolved, not open "
            "questions."
        )
    if revision:
        instruction += (
            " This is a revision, not a restatement. Read the rejected draft and reviewer"
            " findings in the input, then write a materially corrected replacement. "
            "Explicitly resolve each in-scope finding in the relevant document field. Do "
            "not return the rejected draft unchanged."
        )
    return instruction


def reviewer_description(stage, goal, reviewer_evidence):
    """Build the independent reviewer instructions."""
    return (
        f"You are reviewing the {stage} stage ONLY. Its deliverable is: {goal}\n"
        "Inspect the specialist output and relevant source. Report passed only if this stage's requested deliverable is complete. Otherwise report blocked. "
        "For requirements, design, and plan, evaluate the document's completeness and clarity, not whether the implementation is already fixed. "
        "Existing bugs are expected input to these stages and are not a reason to block a complete document. "
        "Do not require work belonging to later stages before passing the current stage. "
        "Scale completeness to the requested change: a small function fix needs a precise algorithm, preserved interfaces, edge-case behavior and verification approach, not diagrams or a new system architecture. Do not invent requirements for visualizations, performance, or new error handling. Block concrete contradictions or missing decisions, not stylistic preferences or optional elaboration. "
        "Implementation passing means ready for external verification, never proof of correctness. "
        "Repair feedback describes a PREVIOUS source version. Check whether the reported issue still exists in CURRENT source. "
        "The original task and README may describe the pre-change bug. When current_changed_source is provided, ground source claims in that actual current text, not in historical descriptions. "
        "Block unresolved source defects or policy violations, but do not block merely because the prior test failed or because the subsequent verification stage has not rerun yet. "
        "Passing examples do not prove a general rule. Inspect input validation for hard-coded test values and reject implementations that leave other members of a disallowed category accepted. Do not claim future delivery stages have executed without completed-stage evidence. "
        + (
            (
                "For requirements, compare each acceptance criterion and blocking "
                "question with the ORIGINAL task. Block omitted explicit requirements, "
                "contradictions, invented constraints or genuine ambiguity that prevents "
                "fulfilling the task; identify the affected task criterion and concrete "
                "consequence in findings. Do not require exact error wording when the "
                "task only requires a nonempty error string. Do not require concurrency, "
                "audit logging or other optional capabilities unless the task requests "
                "them or they are necessary to satisfy an explicit criterion. A writer's "
                "open question is not automatically a blocker: check whether it is "
                "already answered, an implementation choice, or an optional follow-up. "
                "An empty open_questions list is valid. Judge the requested document's "
                "completeness without expanding the requested product scope. "
            )
            if stage == "requirements"
            else ""
        )
        + (
            (
                "For retrospective, completeness means accurately recording observed outcomes, "
                "unresolved risks and proposed follow-up work. It does not mean resolving every "
                "risk or executing those follow-ups. Do not block a complete retrospective "
                "because it records optional concurrency testing, logging, monitoring or other "
                "work outside the original task. Judge the accuracy and completeness of the "
                "record against completed-stage evidence; do not reopen delivered scope. "
            )
            if stage == "retrospective"
            else ""
        )
        + (
            (
                "For this implementation review, call check_current_candidate yourself. Base "
                "your verdict on its CURRENT results rather than copied findings from "
                "previous attempts. "
            )
            if stage == "implement"
            else ""
        )
        + "Preserve important requirements, design decisions and plan details in findings so later stages can use them.\n"
        f"Original intent and accepted upstream documents (reference data):\n{reviewer_evidence}"
    )
