import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { prisma } from '../../../../lib/db';

export const dynamic = 'force-dynamic';

export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  const contact = await prisma.contact.findUnique({
    where: { id: params.id },
    include: { notes: true, activities: true },
  });
  if (!contact) return NextResponse.json({ error: 'not found' }, { status: 404 });
  return NextResponse.json({ contact });
}

const PatchSchema = z.object({
  name: z.string().optional(),
  email: z.string().email().optional(),
  company: z.string().nullable().optional(),
  phone: z.string().nullable().optional(),
  status: z.enum(['lead', 'customer', 'lost']).optional(),
});

export async function PATCH(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json().catch(() => null);
  const parsed = PatchSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  try {
    const contact = await prisma.contact.update({
      where: { id: params.id },
      data: parsed.data as any,
    });
    await prisma.activity.create({
      data: {
        contactId: contact.id,
        kind: 'updated' as any,
        details: JSON.stringify({ source: 'api', patch: parsed.data }),
      },
    });
    return NextResponse.json({ contact });
  } catch (err: any) {
    return NextResponse.json({ error: String(err?.message ?? err) }, { status: 500 });
  }
}

export async function DELETE(_req: NextRequest, { params }: { params: { id: string } }) {
  try {
    await prisma.contact.delete({ where: { id: params.id } });
    return NextResponse.json({ ok: true });
  } catch (err: any) {
    return NextResponse.json({ error: String(err?.message ?? err) }, { status: 500 });
  }
}
