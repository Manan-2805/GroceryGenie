import React from 'react';

type CustomDialogProps = {
  isOpen: boolean;
  title: string;
  message: string;
  isConfirm?: boolean;
  onConfirm?: () => void;
  onClose: () => void;
}

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
      <div className="bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-900 p-6 rounded-2xl shadow-xl max-w-sm w-full mx-4 space-y-4 text-left transform scale-100 transition-all duration-200">
        <div className="space-y-1">
          <h3 className="font-extrabold text-base text-gray-900 dark:text-gray-100">
            {title}
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
            {message}
          </p>
        </div>
        
        <div className="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-900/60">
          {isConfirm && (
            <button
              onClick={() => {
                if (onConfirm) onConfirm();
                onClose();
              }}
              className="px-4 py-1.5 bg-red-600 hover:bg-red-700 dark:bg-red-700 dark:hover:bg-red-800 text-white rounded-lg text-xs font-bold transition-all shadow-sm"
            >
              Confirm
            </button>
          )}
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-gray-100 dark:bg-gray-900 hover:bg-gray-200 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg text-xs font-bold transition-all"
          >
            {isConfirm ? 'Cancel' : 'OK'}
          </button>
        </div>
      </div>
    </div>
  );
};
