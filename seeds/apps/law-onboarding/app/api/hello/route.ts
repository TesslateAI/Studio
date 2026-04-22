import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    message: "Hello from Next.js 16 API",
    timestamp: new Date().toISOString(),
    framework: "Next.js 16.1",
    runtime: "Edge-compatible",
  });
}

export async function POST(request: Request) {
  const body = await request.json();

  return NextResponse.json({
    message: "Data received successfully",
    data: body,
    timestamp: new Date().toISOString(),
  });
}
