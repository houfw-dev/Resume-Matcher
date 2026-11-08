'use client';

import { useParams } from 'next/navigation';
import { CoverLetterStudio } from '@/components/cover-letter/cover-letter-studio';

export default function CoverLetterStudioPage() {
  const params = useParams();
  const resumeId = params?.id as string;

  return <CoverLetterStudio resumeId={resumeId} />;
}
