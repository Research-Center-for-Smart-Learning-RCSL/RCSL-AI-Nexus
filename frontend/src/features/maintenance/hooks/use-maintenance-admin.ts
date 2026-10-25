'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { MAINTENANCE_STATUS_QUERY_KEY } from '@/lib/maintenance';

import {
  enterMaintenance,
  getMaintenance,
  reopenAfterMaintenance,
  getUnknownOperations,
  resetRuntime,
  restoreAfterMaintenance,
  retryMaintenance,
  setMaintenanceMessage,
  type MaintenanceNotice,
} from '../api';

export const maintenanceKeys = {
  admin: ['maintenance', 'admin'] as const,
  unknown: ['maintenance', 'unknown-operations'] as const,
};

export function useMaintenanceAdmin() {
  return useQuery({
    queryKey: maintenanceKeys.admin,
    queryFn: getMaintenance,
    refetchInterval: 2_000,
  });
}

function useInvalidateBoth() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: maintenanceKeys.admin });
    void client.invalidateQueries({ queryKey: MAINTENANCE_STATUS_QUERY_KEY });
  };
}

export function useEnterMaintenance() {
  const invalidate = useInvalidateBoth();
  return useMutation({
    mutationFn: (notice: MaintenanceNotice) => enterMaintenance(notice),
    onSettled: invalidate,
  });
}

export function useReopenAfterMaintenance() {
  const invalidate = useInvalidateBoth();
  return useMutation({ mutationFn: reopenAfterMaintenance, onSettled: invalidate });
}

export function useSetMaintenanceMessage() {
  const invalidate = useInvalidateBoth();
  return useMutation({
    mutationFn: (notice: MaintenanceNotice & { expected_revision: number }) =>
      setMaintenanceMessage(notice),
    onSettled: invalidate,
  });
}

export function useRestoreAfterMaintenance() {
  const invalidate = useInvalidateBoth();
  return useMutation({ mutationFn: restoreAfterMaintenance, onSettled: invalidate });
}

export function useRetryMaintenance() {
  const invalidate = useInvalidateBoth();
  return useMutation({ mutationFn: retryMaintenance, onSettled: invalidate });
}

export function useUnknownOperations() {
  return useQuery({
    queryKey: maintenanceKeys.unknown,
    queryFn: getUnknownOperations,
    refetchInterval: 10_000,
  });
}

export function useResetRuntime() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: resetRuntime,
    onSettled: () => void client.invalidateQueries({ queryKey: maintenanceKeys.unknown }),
  });
}
