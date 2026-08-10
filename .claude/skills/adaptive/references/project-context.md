# Project Context & Guidelines

> Orchestrator defaults, coding standards, recovery and context-limit rules for `/adaptive`.

This file provides overarching guidelines and context for the Adaptive Orchestrator.

## Orchestrator Behavior & Defaults
- **Mode & Interaction:** Default to hybrid mode. The orchestrator should check in with the user at least every 5 iterations or sooner if a major decision arises. Users can explicitly set mode to `interactive`, `autonomous`, or `hybrid` per task.
- **Plan Mode Usage:** For any non-trivial task, begin in Plan Mode (read-only analysis). Only skip Plan Mode for very simple, well-defined tasks.
- **Memory & Logs:** Maintain a log of iterations and outcomes in `./outputs/{task_name}_{timestamp}/` for transparency and post-mortem analysis. Summarize logs when presenting to user to avoid information overload.

## Coding Standards & Quality
- **Language & Style:** Follow the project's coding style (refer to `.stylelintrc` or similar if present). Use idiomatic patterns for the language in use.
- **Testing:** Aim for at least 80% code coverage on new code. Always include critical edge cases in tests.
- **Performance:** If a task has performance requirements, ensure the solution is optimized. No solution should introduce a performance regression; use efficient algorithms and data structures.
- **Security:** All code must handle inputs safely. Follow best practices (e.g., parameterized queries for DB, input validation, avoid insecure functions).
- **Documentation:** Public APIs or complex modules should have clear docstrings or comments. Additionally, major decisions or assumptions should be recorded either in code comments or in the final report to the user.

## Iterative Development Patterns
- **Exploration Phase (Iter 1-3):** Try diverse approaches quickly. It's okay if not all are perfect; the goal is to learn about the problem space.
- **Refinement Phase (Iter 4-7):** Focus on the most promising approach. Fix obvious issues from exploration, tighten the solution to meet requirements.
- **Convergence Phase (Iter 8+):** Polish the solution. Improve performance, clean up code, ensure all tests pass, and edge cases are covered. No new major features should be added here; it's about perfecting what's there.
- These are guidelines; actual iteration counts may vary. The orchestrator should adjust phases based on the situation (e.g., a simple task might converge by iteration 3).

## User Communication
- Always keep the user informed of progress, especially if an iteration might take a long time.
- If the user provides feedback or new info mid-task, incorporate it immediately and adjust the plan (even if mid-iteration).
- If something is truly impossible or conflicts with other requirements, discuss it with the user honestly rather than looping endlessly.

## Failure & Recovery
- If an iteration fails (e.g., code doesn't compile, tests fail badly), log the failure reason and ensure the next iteration addresses it.
- Do not repeat the exact same action expecting a different result; always adjust something (strategy, more context, different agent) when retrying.
- Leverage `learning_context.failed_strategies` to avoid known bad paths. If all known strategies fail, consider reaching out to the user for guidance or re-reading the problem with fresh eyes.

## Context Limit Management
- For large projects, load only relevant portions of the code into context at a time. Use summarization for modules that are too large to read fully, focusing on their interfaces.
- Remove or forget context that is no longer needed as the task progresses, to free up space for new information.

## MCP and Tools
- The orchestrator is expected to use tools (via MCP servers) responsibly. E.g., use the GitHub server to fetch the latest code or commit diff if needed, rather than relying solely on potentially outdated context.
- Clean up any temporary MCP resources after use to avoid side effects (for example, if a scratch database was used for testing, ensure it's properly closed or transactions rolled back).

---

*End of CLAUDE.md.*
```

## Example Usage Scenarios

The orchestrator prompt is versatile and can handle a range of tasks. Here are some example invocations and how it would behave:

* **Simple Bug Fix (Interactive Preferred):**
  **User input:** `/adaptive "Fix the null pointer exception when clicking the Save button"`
  **Behavior:** Recognizes it's a specific bug. Enters Plan Mode to locate relevant file and line. Asks user for any context if needed (e.g., "Do you have steps to reproduce?"). Then autonomously fixes the bug using Code Generation Agent, runs tests, and presents the patch.

* **Complex Feature (Hybrid):**
  **User input:** `/adaptive "Implement a new user authentication system with OAuth support" mode:hybrid`
  **Behavior:** Plan Mode kicks in to outline steps: design DB schema, integrate OAuth library, update UI flows, etc., and identifies unclear details (like which OAuth providers?). It asks user a couple of clarifying questions (interactive). Then proceeds to implement in parallel: one agent codes backend, another works on front-end, etc. Evaluator checks security and correctness. It loops until the feature is fully working and secure. Provides periodic updates given the complexity.

* **Optimization Task (Autonomous with Infinite Iteration):**
  **User input:** `/adaptive "Optimize the image processing module for faster runtime" mode:autonomous iterations:infinite`
  **Behavior:** The orchestrator sees the user allowed infinite refinement. It enters Plan Mode to understand the module and identify possible optimizations (algorithmic improvements, parallelization, etc.). It then iteratively refines the code, each time measuring or estimating performance gains (could use a Performance Agent or built-in timing in tests). It continues until improvements level off (stagnation detected), then pauses and reports: "We've improved performance by X%. Further improvements have diminishing returns. Do you want to continue optimizing or stop here?" This ensures it doesn't waste time once near a local optimum.

* **Research & Prototype (Interactive):**
  **User input:** `/adaptive "Research and prototype three different approaches for implementing a recommender system"`
  **Behavior:** Recognizing an open-ended research task, the orchestrator stays mostly in interactive mode. It might not write production code immediately. Instead, it could spawn research agents to outline each approach (e.g., content-based vs collaborative filtering vs hybrid) and discuss pros/cons. It will present findings to the user and perhaps a simple prototype for each. The user can then decide which to pursue further, illustrating how the orchestrator can aid in decision-making, not just coding.

## Conclusion

This **Next-Generation Agentic Orchestrator** prompt is designed to push Claude Code to its limits, enabling hours of productive autonomous work with safety nets and quality checks that mimic a senior engineer's oversight. It implements state-of-the-art techniques from AI research on iterative prompt improvement and autonomous agents, all within the practical constraints of the Claude environment.

By using this orchestrator, users can expect:

* Dramatically reduced need for manual babysitting of the AI (it will self-iterate and correct).
* Higher quality outputs that meet strict standards.
* Enhanced control and transparency, as the process is explainable and interruptible at any point.
* Continuous learning and improvement, meaning the more you use it, the better it gets.

This prompt is a culmination of best practices and innovations – truly a **magnum opus** for building agentic workflows in Claude Code. Use it to tackle your toughest coding challenges with confidence that the AI will plan wisely, code diligently, evaluate rigorously, and always loop back to make things even better.
