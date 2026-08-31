import { z } from "zod";

// Server-side only. The internal FastAPI URL must never reach browser
// JavaScript, so it is deliberately kept out of public build-time variables.

const LOCAL_BACKEND_URL = "http://127.0.0.1:8000";

const serverEnvSchema = z
  .object({
    NODE_ENV: z
      .enum(["development", "test", "production"])
      .default("development"),
    CONTENTOS_INTERNAL_API_URL: z
      .string()
      .url("CONTENTOS_INTERNAL_API_URL must be a valid URL")
      .startsWith("http", "CONTENTOS_INTERNAL_API_URL must be an http(s) URL")
      .optional(),
  })
  .superRefine((env, ctx) => {
    if (
      env.NODE_ENV === "production" &&
      env.CONTENTOS_INTERNAL_API_URL === undefined
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["CONTENTOS_INTERNAL_API_URL"],
        message: "CONTENTOS_INTERNAL_API_URL is required in production",
      });
    }
  })
  .transform((env) => ({
    nodeEnv: env.NODE_ENV,
    internalApiUrl: env.CONTENTOS_INTERNAL_API_URL ?? LOCAL_BACKEND_URL,
  }));

export type ServerEnv = z.infer<typeof serverEnvSchema>;

export function parseServerEnv(
  source: Record<string, string | undefined>,
): ServerEnv {
  const result = serverEnvSchema.safeParse(source);
  if (!result.success) {
    const issues = result.error.issues
      .map(
        (issue) => `${issue.path.join(".") || "environment"}: ${issue.message}`,
      )
      .join("; ");
    throw new Error(`Invalid ContentOS admin environment: ${issues}`);
  }
  return result.data;
}

let cachedEnv: ServerEnv | null = null;

export function getServerEnv(): ServerEnv {
  cachedEnv ??= parseServerEnv(process.env);
  return cachedEnv;
}
