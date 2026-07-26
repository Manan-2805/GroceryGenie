import React from 'react';

type CustomDialogProps = {
  isOpen: boolean;
  title: string;
  message: string;
  isConfirm?: boolean;
  onConfirm?: () => void;
  onClose: () => void;
};

export const CustomDialog: React.FC<CustomDialogProps> = ({
  isOpen,
  title,
  message,
  isConfirm = false,
  onConfirm,
  onClose,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="glass-card p-6 max-w-sm w-full mx-4 space-y-4 text-left">
        <div className="space-y-1">
          <h3 className="font-semibold text-base text-heading">{title}</h3>
          <p className="text-xs text-muted leading-relaxed">{message}</p>
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-border/60">
          {isConfirm && (
            <button
              onClick={() => {
                if (onConfirm) onConfirm();
                onClose();
              }}
              className="px-4 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-semibold transition-all"
            >
              Confirm
            </button>
          )}
          <button onClick={onClose} className="btn-secondary py-1.5 px-4">
            {isConfirm ? 'Cancel' : 'OK'}
          </button>
        </div>
      </div>
    </div>
  );
};
