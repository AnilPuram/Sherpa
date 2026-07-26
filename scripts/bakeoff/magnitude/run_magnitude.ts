/**
 * Run WebVoyager round-2 tasks with Magnitude.
 *
 * Tracks:
 * - equal-planner (default): OpenRouter openai-generic with BAKEOFF_PLANNER_MODEL
 * - recommended-vl: Anthropic Claude (requires ANTHROPIC_API_KEY); label separately
 *
 * Usage:
 *   bun install
 *   bun run run_magnitude.ts --real-model
 *   bun run run_magnitude.ts --real-model --track recommended-vl
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { startBrowserAgent } from "magnitude-core";
import { z } from "zod";

const ROOT = path.resolve(import.meta.dir, "../../..");
const DEFAULT_MANIFEST = path.join(ROOT, "eval/webvoyager-round2.jsonl");
const DEFAULT_MODEL = process.env.BAKEOFF_PLANNER_MODEL ?? "qwen/qwen3.5-35b-a3b";
const DEFAULT_VL_MODEL = process.env.BAKEOFF_MAGNITUDE_VL_MODEL ?? "claude-sonnet-4-20250514";

type BakeoffTask = {
  id: string;
  web_name: string;
  ques: string;
  web: string;
};

type BakeoffResult = {
  id: string;
  agent: "magnitude";
  model: string;
  answer: string | null;
  outcome: "done" | "failed" | "max_steps" | "skipped" | "error";
  steps: number;
  cost_usd: number | null;
  error: string | null;
  track: string;
  artifacts: string | null;
};

function parseArgs(argv: string[]) {
  const args = {
    manifest: DEFAULT_MANIFEST,
    artifacts: path.join(ROOT, "artifacts/bakeoff-magnitude-round2"),
    output: path.join(ROOT, "artifacts/bakeoff-magnitude-round2/report.json"),
    model: DEFAULT_MODEL,
    track: "equal-planner" as "equal-planner" | "recommended-vl",
    maxSteps: 20,
    timeoutSec: 480,
    taskIds: [] as string[],
    realModel: false,
    headed: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    if (a === "--manifest") args.manifest = path.resolve(next());
    else if (a === "--artifacts") args.artifacts = path.resolve(next());
    else if (a === "--output") args.output = path.resolve(next());
    else if (a === "--model") args.model = next();
    else if (a === "--track") {
      const track = next();
      if (track !== "equal-planner" && track !== "recommended-vl") {
        throw new Error(`Invalid --track ${track}`);
      }
      args.track = track;
    } else if (a === "--max-steps") args.maxSteps = Number(next());
    else if (a === "--timeout-sec") args.timeoutSec = Number(next());
    else if (a === "--task-id") args.taskIds.push(next());
    else if (a === "--real-model") args.realModel = true;
    else if (a === "--headed") args.headed = true;
    else if (a === "--help" || a === "-h") {
      console.log(`Usage: bun run run_magnitude.ts --real-model [options]
  --manifest PATH
  --artifacts DIR
  --output PATH
  --model MODEL
  --track equal-planner|recommended-vl
  --max-steps N
  --task-id ID (repeatable)
  --headed
  --real-model`);
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${a}`);
    }
  }
  return args;
}

async function loadTasks(manifest: string): Promise<BakeoffTask[]> {
  const text = await readFile(manifest, "utf8");
  const tasks: BakeoffTask[] = [];
  const seen = new Set<string>();
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const raw = JSON.parse(line) as BakeoffTask;
    if (seen.has(raw.id)) throw new Error(`Duplicate task id: ${raw.id}`);
    seen.add(raw.id);
    tasks.push(raw);
  }
  if (tasks.length === 0) throw new Error(`Empty manifest: ${manifest}`);
  return tasks;
}

function safeId(taskId: string): string {
  return taskId.replace(/[^A-Za-z0-9_.-]+/g, "_");
}

function buildLlm(track: "equal-planner" | "recommended-vl", model: string) {
  if (track === "recommended-vl") {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      throw new Error("recommended-vl track requires ANTHROPIC_API_KEY");
    }
    return {
      provider: "anthropic" as const,
      options: {
        model: model || DEFAULT_VL_MODEL,
        apiKey,
        temperature: 0.2,
      },
    };
  }
  const apiKey = process.env.OPENROUTER_API_KEY;
  if (!apiKey) {
    throw new Error("equal-planner track requires OPENROUTER_API_KEY");
  }
  return {
    provider: "openai-generic" as const,
    options: {
      model,
      baseUrl: "https://openrouter.ai/api/v1",
      apiKey,
      temperature: 0.2,
      headers: {
        "HTTP-Referer": "https://github.com/sherpa-bakeoff",
        "X-Title": "Sherpa Bakeoff",
      },
    },
  };
}

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`${label} timed out after ${Math.round(ms / 1000)}s`));
    }, ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}

async function runOne(opts: {
  task: BakeoffTask;
  model: string;
  track: "equal-planner" | "recommended-vl";
  maxSteps: number;
  headed: boolean;
  taskDir: string;
  timeoutMs: number;
}): Promise<BakeoffResult> {
  const { task, model, track, headed, taskDir, timeoutMs } = opts;
  let agent: Awaited<ReturnType<typeof startBrowserAgent>> | null = null;
  const trackName =
    track === "equal-planner" ? "equal-planner" : "magnitude-recommended-vl";
  try {
    const llm = buildLlm(track, model);
    agent = await startBrowserAgent({
      llm,
      narrate: false,
      browser: {
        launchOptions: { headless: !headed },
      },
    });
    await agent.nav(task.web);
    await withTimeout(
      agent.act(
        [
          `Complete this information-retrieval web task in at most ${opts.maxSteps} browser actions.`,
          `Prefer finishing early once the answer is visible.`,
          `Do not keep scrolling the same page without progress.`,
          `Return only facts visible on the pages you visit.`,
          `When finished, the answer must be specific and complete.`,
          ``,
          `Task: ${task.ques}`,
        ].join("\n"),
      ),
      timeoutMs,
      `act(${task.id})`,
    );
    const extracted = await withTimeout(
      agent.extract(
        "Provide the concise final answer to the task based on what you found. If incomplete, say what is missing.",
        z.object({
          answer: z.string(),
          complete: z.boolean(),
        }),
      ),
      120_000,
      `extract(${task.id})`,
    );
    const result: BakeoffResult = {
      id: task.id,
      agent: "magnitude",
      model: llm.options.model,
      answer: extracted.answer,
      outcome: extracted.complete ? "done" : "failed",
      steps: 0,
      cost_usd: null,
      error: null,
      track: trackName,
      artifacts: taskDir,
    };
    await writeFile(
      path.join(taskDir, "extract.json"),
      JSON.stringify(extracted, null, 2) + "\n",
    );
    return result;
  } catch (err) {
    const message = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
    const timedOut = /timed out/i.test(message);
    const incompatible =
      /visual|ground|coordinate|not compatible|unsupported model/i.test(message);
    return {
      id: task.id,
      agent: "magnitude",
      model,
      answer: null,
      outcome: timedOut ? "max_steps" : "error",
      steps: 0,
      cost_usd: null,
      error: incompatible
        ? `${message} (If equal-planner model is not visually grounded, re-run with --track recommended-vl and do not mix scores.)`
        : message,
      track: trackName,
      artifacts: taskDir,
    };
  } finally {
    if (agent) {
      try {
        await agent.stop();
      } catch {
        /* ignore */
      }
    }
    // Let Playwright tear down before the next task opens a new browser.
    await Bun.sleep(2500);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.realModel) {
    console.error(
      "run_magnitude.ts requires --real-model; paid model calls are never implicit",
    );
    process.exit(1);
  }

  let model = args.model;
  if (args.track === "recommended-vl" && args.model === DEFAULT_MODEL) {
    model = DEFAULT_VL_MODEL;
  }

  let tasks = await loadTasks(args.manifest);
  if (args.taskIds.length) {
    const wanted = new Set(args.taskIds);
    tasks = tasks.filter((t) => wanted.has(t.id));
    const missing = [...wanted].filter((id) => !tasks.some((t) => t.id === id));
    if (missing.length) throw new Error(`Unknown task id(s): ${missing.join(", ")}`);
  }

  await mkdir(args.artifacts, { recursive: true });
  const results: BakeoffResult[] = [];

  for (const task of tasks) {
    const taskDir = path.join(args.artifacts, safeId(task.id));
    await mkdir(taskDir, { recursive: true });
    console.log(`[magnitude/${args.track}] ${task.id}`);
    const result = await runOne({
      task,
      model,
      track: args.track,
      maxSteps: args.maxSteps,
      headed: args.headed,
      taskDir,
      timeoutMs: args.timeoutSec * 1000,
    });
    await writeFile(
      path.join(taskDir, "result.json"),
      JSON.stringify(result, null, 2) + "\n",
    );
    results.push(result);
    console.log(
      `  outcome=${result.outcome} answer=${JSON.stringify((result.answer ?? "").slice(0, 120))}`,
    );
  }

  const report = {
    agent: "magnitude",
    track: args.track === "equal-planner" ? "equal-planner" : "magnitude-recommended-vl",
    model,
    manifest: args.manifest,
    max_steps: args.maxSteps,
    results,
  };
  await mkdir(path.dirname(args.output), { recursive: true });
  await writeFile(args.output, JSON.stringify(report, null, 2) + "\n");
  console.log(`Wrote ${args.output}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
