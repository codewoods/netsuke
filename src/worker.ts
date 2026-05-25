// CF Worker entry: validate Access JWTs and route traffic to PdfConverter.
//
// The container is the FastAPI app on port 8000. Cloudflare Access sits
// in front of this Worker (configured in the dashboard, not in code), so
// every request reaching here should already be allowed. We still verify
// the JWT signature and audience so a misconfigured route fails closed.

import { Container, getRandom } from "@cloudflare/containers";

import { validateAccessRequest, type AccessEnv } from "./access";

const CONTAINER_INSTANCE_COUNT = 1;

export class PdfConverter extends Container<Env> {
  // Container listens on port 8000 inside the image (uvicorn).
  defaultPort = 8000;
  // Sleep the container after 5 min idle to free instance slots.
  sleepAfter = "5m";
}

interface Env extends AccessEnv {
  PDF_CONVERTER: DurableObjectNamespace<PdfConverter>;
  CONTAINER_INSTANCES?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // Keep auth at the Worker boundary before any request reaches the container.
    const access = await validateAccessRequest(request, env);
    if (!access.ok) return new Response(access.body, { status: access.status });

    // Conversion is stateless, so requests can spread across configured
    // instances while each instance still gets warm reuse.
    const instances = parseContainerInstances(env.CONTAINER_INSTANCES);
    const container = await getRandom(env.PDF_CONVERTER, instances);
    return container.fetch(request);
  },
} satisfies ExportedHandler<Env>;

const parseContainerInstances = (value: string | undefined): number => {
  // Wrangler vars are strings; invalid values fall back to the checked-in config.
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0
    ? parsed
    : CONTAINER_INSTANCE_COUNT;
};
