import { getMockResponse } from './request';
import { mockRpaTaskDetail, mockRpaTasks } from '../mock/rpa';

export const fetchRpaTasks = () => getMockResponse(mockRpaTasks, 'rpa.tasks');
export const fetchRpaTaskDetail = () => getMockResponse(mockRpaTaskDetail, 'rpa.task.detail');
