'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { MAINTENANCE_STATUS_QUERY_KEY } from '@/lib/maintenance';

import {
  enterMaintenance,
  getMaintenance,
  reopenAfterMaintenance,
  setMaintenanceMessage,
  type MaintenanceNotice,
} from '../api';

export const maintenanceKeys = { admin: ['maintenance', 'admin'] as const };

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
