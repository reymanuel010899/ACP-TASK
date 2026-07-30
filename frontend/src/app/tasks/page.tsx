import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import NewTaskButton from "@/components/shell/NewTaskButton";
import TaskDetailContent from "@/components/tasks/TaskDetailContent";
import TaskDetailRightPanel from "@/components/tasks/TaskDetailRightPanel";

export const metadata: Metadata = {
  title: "Task Detail — Console",
};

export default function TaskDetailPage() {
  return (
    <AppShell
      active="tasks"
      topBarAction={<NewTaskButton />}
      rightPanel={<TaskDetailRightPanel />}
    >
      <TaskDetailContent />
    </AppShell>
  );
}
