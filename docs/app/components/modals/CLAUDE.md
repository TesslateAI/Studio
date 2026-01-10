# Modals - AI Agent Context

## Creating a New Modal

```typescript
// NewModal.tsx
import { useState } from 'react';
import { X, IconName } from 'lucide-react';

interface NewModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (data: DataType) => void;
  initialData?: DataType;
}

export function NewModal({ isOpen, onClose, onConfirm, initialData }: NewModalProps) {
  const [formData, setFormData] = useState(initialData || { field: '' });
  const [isLoading, setIsLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async () => {
    setIsLoading(true);
    try {
      await onConfirm(formData);
      onClose();
    } catch (error) {
      toast.error('Operation failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={() => !isLoading && onClose()}
    >
      <div
        className="bg-[var(--surface)] p-8 rounded-3xl max-w-md w-full"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 bg-[var(--primary)]/20 rounded-xl flex items-center justify-center">
              <IconName size={24} className="text-[var(--primary)]" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-[var(--text)]">Modal Title</h2>
              <p className="text-sm text-gray-400">Description here</p>
            </div>
          </div>
          {!isLoading && (
            <button onClick={onClose} className="text-gray-400 hover:text-white">
              <X size={20} />
            </button>
          )}
        </div>

        {/* Form */}
        <div className="mb-6 space-y-4">
          <input
            type="text"
            value={formData.field}
            onChange={(e) => setFormData({ ...formData, field: e.target.value })}
            placeholder="Enter value"
            disabled={isLoading}
            className="w-full px-4 py-3 bg-[var(--bg)] border border-[var(--border-color)] rounded-xl"
          />
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={isLoading}
            className="flex-1 bg-white/5 border border-white/10 py-3 rounded-xl"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={isLoading}
            className="flex-1 bg-[var(--primary)] py-3 rounded-xl"
          >
            {isLoading ? 'Loading...' : 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

## Multi-Step Modal

For wizards like deployment:

```typescript
export function WizardModal({ isOpen, onClose }: Props) {
  const [step, setStep] = useState(1);
  const [formData, setFormData] = useState({});

  const nextStep = () => setStep(s => s + 1);
  const prevStep = () => setStep(s => s - 1);

  return (
    <div className="modal-backdrop">
      <div className="modal-content">
        {/* Progress indicator */}
        <div className="flex gap-2 mb-6">
          {[1, 2, 3].map(s => (
            <div
              key={s}
              className={`flex-1 h-2 rounded ${s <= step ? 'bg-orange-500' : 'bg-gray-700'}`}
            />
          ))}
        </div>

        {/* Step content */}
        {step === 1 && <Step1 data={formData} onChange={setFormData} />}
        {step === 2 && <Step2 data={formData} onChange={setFormData} />}
        {step === 3 && <Step3 data={formData} onChange={setFormData} />}

        {/* Navigation */}
        <div className="flex gap-3 mt-6">
          {step > 1 && <button onClick={prevStep}>Back</button>}
          {step < 3 && <button onClick={nextStep}>Next</button>}
          {step === 3 && <button onClick={() => onConfirm(formData)}>Finish</button>}
        </div>
      </div>
    </div>
  );
}
```

## Focus Management

Trap focus within modal:

```typescript
import { useEffect, useRef } from 'react';

export function Modal({ isOpen }: Props) {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const focusableElements = modalRef.current?.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );

    if (!focusableElements || focusableElements.length === 0) return;

    const firstElement = focusableElements[0] as HTMLElement;
    const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;

    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;

      if (e.shiftKey) {
        if (document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        }
      } else {
        if (document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    };

    document.addEventListener('keydown', handleTab);
    firstElement.focus();

    return () => document.removeEventListener('keydown', handleTab);
  }, [isOpen]);

  return <div ref={modalRef}>{/* Modal content */}</div>;
}
```

## Form Validation

```typescript
const [errors, setErrors] = useState<Record<string, string>>({});

const validate = (): boolean => {
  const newErrors: Record<string, string> = {};

  if (!formData.name.trim()) {
    newErrors.name = 'Name is required';
  }

  if (!formData.email.match(/\S+@\S+\.\S+/)) {
    newErrors.email = 'Invalid email';
  }

  setErrors(newErrors);
  return Object.keys(newErrors).length === 0;
};

const handleSubmit = async () => {
  if (!validate()) return;

  // Proceed with submission
};

// Display errors
<input />
{errors.name && <span className="text-red-500 text-sm">{errors.name}</span>}
```

## Testing Modals

```typescript
import { render, screen, fireEvent } from '@testing-library/react';

test('opens and closes modal', () => {
  const onClose = jest.fn();

  const { rerender } = render(
    <Modal isOpen={false} onClose={onClose} />
  );

  // Modal not visible
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

  // Open modal
  rerender(<Modal isOpen={true} onClose={onClose} />);
  expect(screen.getByRole('dialog')).toBeInTheDocument();

  // Close via backdrop
  fireEvent.click(screen.getByRole('dialog').parentElement);
  expect(onClose).toHaveBeenCalled();
});

test('submits form data', async () => {
  const onConfirm = jest.fn();

  render(<Modal isOpen={true} onConfirm={onConfirm} />);

  fireEvent.change(screen.getByPlaceholderText('Enter name'), {
    target: { value: 'Test Name' }
  });

  fireEvent.click(screen.getByText('Confirm'));

  await waitFor(() => {
    expect(onConfirm).toHaveBeenCalledWith({ name: 'Test Name' });
  });
});
```

## Common Issues

### Modal Not Closing on Backdrop Click

Check:
1. `onClick` on backdrop div
2. `e.stopPropagation()` on modal content
3. Not disabled during loading

```typescript
// Backdrop
<div onClick={() => !isLoading && onClose()}>
  {/* Modal content */}
  <div onClick={(e) => e.stopPropagation()}>
    {/* Prevents backdrop click */}
  </div>
</div>
```

### Z-Index Issues

Ensure modal has higher z-index than other elements:
```typescript
className="fixed inset-0 z-50"  // Modal
className="fixed inset-0 z-40"  // Other overlays
```

### Form Reset on Close

Reset form state when closing:
```typescript
const handleClose = () => {
  setFormData(initialData);
  setErrors({});
  onClose();
};
```

---

**Remember**: Modals should be lightweight and focused. For complex flows, consider using separate pages instead.
