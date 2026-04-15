import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { prisma } from '../../../lib/db';

export const dynamic = 'force-dynamic';

const NoteSchema = z.object({
  contact_id: z.string().min(1),
  body: z.string().min(1),
});

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = NoteSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  try {
    const note = await prisma.note.create({
      data: { contactId: parsed.data.contact_id, body: parsed.data.body },
    });
    await prisma.activity.create({
      data: {
        contactId: parsed.data.contact_id,
        kind: 'note_added' as any,
        details: JSON.stringify({ source: 'api', note_id: note.id }),
      },
    });
    return NextResponse.json({ note }, { status: 201 });
  } catch (err: any) {
    return NextResponse.json({ error: String(err?.message ?? err) }, { status: 500 });
  }
}
