type HealthResponse = {
  status?: string;
};

async function getBackendHealth(): Promise<string> {
  try {
    const response = await fetch("http://localhost:8000/health", {
      cache: "no-store"
    });

    if (!response.ok) {
      return "error";
    }

    const data = (await response.json()) as HealthResponse;
    return data.status === "ok" ? "ok" : "error";
  } catch {
    return "error";
  }
}

export default async function Home() {
  const health = await getBackendHealth();

  return (
    <main className="min-h-screen bg-neutral-50 text-neutral-950">
      <section className="mx-auto flex min-h-screen w-full max-w-3xl flex-col justify-center px-6">
        <p className="mb-3 text-sm font-medium uppercase text-teal-700">
          Local compliance workspace
        </p>
        <h1 className="text-4xl font-semibold">Compliance Reviewer</h1>
        <div className="mt-8 border-l-4 border-teal-600 bg-white px-5 py-4 shadow-sm">
          <p className="text-sm font-medium text-neutral-600">Backend status</p>
          <p className="mt-1 text-2xl font-semibold">{health}</p>
        </div>
      </section>
    </main>
  );
}
