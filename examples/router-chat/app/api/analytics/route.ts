import { analytics } from "../chat/store";

export const runtime = "nodejs";

export async function GET() {
  return Response.json(analytics.snapshot());
}
