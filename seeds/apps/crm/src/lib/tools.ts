import { prisma } from './db';

export const CRM_TOOLS = [
  {
    type: 'function' as const,
    function: {
      name: 'list_contacts',
      description: 'List contacts, optionally filtered by status or search query.',
      parameters: {
        type: 'object',
        properties: {
          status: {
            type: 'string',
            enum: ['lead', 'customer', 'lost'],
            description: 'Optional contact status filter.',
          },
          query: {
            type: 'string',
            description: 'Optional case-insensitive search against name, email, or company.',
          },
          limit: { type: 'integer', minimum: 1, maximum: 100, default: 20 },
        },
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'create_contact',
      description: 'Create a new CRM contact.',
      parameters: {
        type: 'object',
        required: ['name', 'email'],
        properties: {
          name: { type: 'string' },
          email: { type: 'string' },
          company: { type: 'string' },
          phone: { type: 'string' },
          status: { type: 'string', enum: ['lead', 'customer', 'lost'], default: 'lead' },
        },
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'update_contact',
      description: 'Update fields on an existing contact by id.',
      parameters: {
        type: 'object',
        required: ['id'],
        properties: {
          id: { type: 'string' },
          patch: {
            type: 'object',
            properties: {
              name: { type: 'string' },
              email: { type: 'string' },
              company: { type: 'string' },
              phone: { type: 'string' },
              status: { type: 'string', enum: ['lead', 'customer', 'lost'] },
            },
          },
        },
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'delete_contact',
      description: 'Delete a contact by id.',
      parameters: {
        type: 'object',
        required: ['id'],
        properties: { id: { type: 'string' } },
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'add_note',
      description: 'Attach a note to a contact.',
      parameters: {
        type: 'object',
        required: ['contact_id', 'text'],
        properties: {
          contact_id: { type: 'string' },
          text: { type: 'string' },
        },
      },
    },
  },
  {
    type: 'function' as const,
    function: {
      name: 'get_contact_activity',
      description: 'Return recent activity entries for a contact.',
      parameters: {
        type: 'object',
        required: ['contact_id'],
        properties: {
          contact_id: { type: 'string' },
          limit: { type: 'integer', minimum: 1, maximum: 100, default: 20 },
        },
      },
    },
  },
];

async function logActivity(contactId: string, kind: string, details: unknown) {
  await prisma.activity.create({
    data: {
      contactId,
      kind: kind as any,
      details: JSON.stringify(details ?? {}),
    },
  });
}

export async function dispatchTool(name: string, argsJson: string): Promise<string> {
  let args: any = {};
  try {
    args = argsJson ? JSON.parse(argsJson) : {};
  } catch (e) {
    return JSON.stringify({ ok: false, error: `invalid tool args json: ${String(e)}` });
  }

  try {
    switch (name) {
      case 'list_contacts': {
        const where: any = {};
        if (args.status) where.status = args.status;
        if (args.query) {
          where.OR = [
            { name: { contains: args.query } },
            { email: { contains: args.query } },
            { company: { contains: args.query } },
          ];
        }
        const rows = await prisma.contact.findMany({
          where,
          orderBy: { createdAt: 'desc' },
          take: Math.min(args.limit ?? 20, 100),
        });
        return JSON.stringify({ ok: true, contacts: rows });
      }
      case 'create_contact': {
        const created = await prisma.contact.create({
          data: {
            name: args.name,
            email: args.email,
            company: args.company ?? null,
            phone: args.phone ?? null,
            status: (args.status ?? 'lead') as any,
          },
        });
        await logActivity(created.id, 'created', { source: 'agent', ...args });
        return JSON.stringify({ ok: true, contact: created });
      }
      case 'update_contact': {
        const updated = await prisma.contact.update({
          where: { id: args.id },
          data: args.patch ?? {},
        });
        await logActivity(updated.id, 'updated', { source: 'agent', patch: args.patch });
        return JSON.stringify({ ok: true, contact: updated });
      }
      case 'delete_contact': {
        await prisma.contact.delete({ where: { id: args.id } });
        return JSON.stringify({ ok: true, id: args.id });
      }
      case 'add_note': {
        const note = await prisma.note.create({
          data: { contactId: args.contact_id, body: args.text },
        });
        await logActivity(args.contact_id, 'note_added', { source: 'agent', note_id: note.id });
        return JSON.stringify({ ok: true, note });
      }
      case 'get_contact_activity': {
        const rows = await prisma.activity.findMany({
          where: { contactId: args.contact_id },
          orderBy: { createdAt: 'desc' },
          take: Math.min(args.limit ?? 20, 100),
        });
        return JSON.stringify({ ok: true, activities: rows });
      }
      default:
        return JSON.stringify({ ok: false, error: `unknown tool: ${name}` });
    }
  } catch (err: any) {
    return JSON.stringify({ ok: false, error: String(err?.message ?? err) });
  }
}
