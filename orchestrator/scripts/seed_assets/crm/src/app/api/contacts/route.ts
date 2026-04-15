import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { prisma } from '../../../lib/db';

export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const q = searchParams.get('q') ?? '';
  const status = searchParams.get('status') ?? '';

  const where: any = {};
  if (status && ['lead', 'customer', 'lost'].includes(status)) where.status = status;
  if (q) {
    where.OR = [
      { name: { contains: q } },
      { email: { contains: q } },
      { company: { contains: q } },
    ];
  }
  const contacts = await prisma.contact.findMany({
    where,
    orderBy: { createdAt: 'desc' },
    take: 200,
  });
  return NextResponse.json({ contacts });
}

const CreateSchema = z.object({
  name: z.string().min(1),
  email: z.string().email(),
  company: z.string().optional().nullable(),
  phone: z.string().optional().nullable(),
  status: z.enum(['lead', 'customer', 'lost']).optional(),
});

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = CreateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  try {
    const contact = await prisma.contact.create({
      data: {
        name: parsed.data.name,
        email: parsed.data.email,
        company: parsed.data.company ?? null,
        phone: parsed.data.phone ?? null,
        status: (parsed.data.status ?? 'lead') as any,
      },
    });
    await prisma.activity.create({
      data: {
        contactId: contact.id,
        kind: 'created' as any,
        details: JSON.stringify({ source: 'api' }),
      },
    });
    return NextResponse.json({ contact }, { status: 201 });
  } catch (err: any) {
    return NextResponse.json({ error: String(err?.message ?? err) }, { status: 500 });
  }
}
