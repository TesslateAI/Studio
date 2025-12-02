import {
  SiNextdotjs,
  SiReact,
  SiTypescript,
  SiTailwindcss,
  SiVite,
  SiFastapi,
  SiPython,
  SiPostgresql,
  SiGo,
  SiRedis,
  SiSupabase,
  SiOpenai,
  SiStripe,
  SiPrometheus,
  SiGrafana,
  SiDocker,
  SiJavascript,
  SiNodedotjs,
  SiMongodb,
  SiMysql,
  SiVercel,
  SiNetlify,
  SiGithub,
  SiGitlab,
  SiKubernetes,
  SiNginx,
  SiExpress,
  SiDjango,
  SiFlask,
  SiRuby,
  SiPhp,
  SiLaravel,
  SiVuedotjs,
  SiAngular,
  SiSvelte,
  SiFirebase,
  SiGraphql,
  SiPrisma,
  SiTerraform,
  SiAnsible,
  SiJenkins,
  SiRust,
  SiElasticsearch,
  SiRabbitmq,
  SiCloudflare,
  SiHeroku,
  SiLinux,
  SiApple,
  SiAndroid,
  SiSlack,
  SiDiscord,
  SiFigma,
  SiJest,
  SiWebpack,
  SiNpm,
  SiYarn,
  SiSass,
  SiBootstrap,
  SiRedux,
  SiCss3,
  SiHtml5,
  SiAmazonwebservices,
  SiGooglecloud,
  SiFlutter,
  SiDart,
  SiKotlin,
  SiSwift,
} from 'react-icons/si';
import {
  DiTerminal,
} from 'react-icons/di';
import {
  BiEnvelope,
} from 'react-icons/bi';
import {
  HiOutlineCpuChip,
  HiOutlineServerStack,
  HiOutlineCube,
  HiOutlineCircleStack,
} from 'react-icons/hi2';
import type { IconType } from 'react-icons/lib';

// Map tech stack names to icons
const techIconMap: Record<string, IconType> = {
  // JavaScript/TypeScript ecosystem
  'nextjs': SiNextdotjs,
  'next.js': SiNextdotjs,
  'next.js 15': SiNextdotjs,
  'next.js 14': SiNextdotjs,
  'react': SiReact,
  'react 19': SiReact,
  'react 18': SiReact,
  'typescript': SiTypescript,
  'javascript': SiJavascript,
  'node.js': SiNodedotjs,
  'nodejs': SiNodedotjs,
  'node': SiNodedotjs,
  'express': SiExpress,
  'express.js': SiExpress,
  'vite': SiVite,

  // CSS/Styling
  'tailwind': SiTailwindcss,
  'tailwind css': SiTailwindcss,
  'tailwindcss': SiTailwindcss,
  'sass': SiSass,
  'scss': SiSass,
  'css': SiCss3,
  'css3': SiCss3,
  'html': SiHtml5,
  'html5': SiHtml5,
  'bootstrap': SiBootstrap,

  // Frontend frameworks
  'vue': SiVuedotjs,
  'vue.js': SiVuedotjs,
  'angular': SiAngular,
  'svelte': SiSvelte,
  'sveltekit': SiSvelte,

  // State management
  'redux': SiRedux,

  // Python ecosystem
  'python': SiPython,
  'fastapi': SiFastapi,
  'django': SiDjango,
  'flask': SiFlask,
  'uvicorn': SiPython,
  'pydantic': SiPython,

  // Go
  'go': SiGo,
  'golang': SiGo,
  'chi': SiGo,
  'chi router': SiGo,
  'air': SiGo,

  // Rust
  'rust': SiRust,

  // Ruby
  'ruby': SiRuby,

  // PHP
  'php': SiPhp,
  'laravel': SiLaravel,

  // Mobile
  'swift': SiSwift,
  'android': SiAndroid,
  'flutter': SiFlutter,
  'dart': SiDart,
  'kotlin': SiKotlin,
  'react native': SiReact,

  // Databases
  'postgresql': SiPostgresql,
  'postgres': SiPostgresql,
  'mysql': SiMysql,
  'mongodb': SiMongodb,
  'mongo': SiMongodb,
  'redis': SiRedis,
  'elasticsearch': SiElasticsearch,
  'prisma': SiPrisma,

  // Cloud & Hosting
  'aws': SiAmazonwebservices,
  'amazon web services': SiAmazonwebservices,
  'gcp': SiGooglecloud,
  'google cloud': SiGooglecloud,
  'vercel': SiVercel,
  'netlify': SiNetlify,
  'heroku': SiHeroku,
  'cloudflare': SiCloudflare,
  'firebase': SiFirebase,

  // DevOps & Infrastructure
  'docker': SiDocker,
  'kubernetes': SiKubernetes,
  'k8s': SiKubernetes,
  'nginx': SiNginx,
  'terraform': SiTerraform,
  'ansible': SiAnsible,
  'jenkins': SiJenkins,
  'github actions': SiGithub,
  'gitlab ci': SiGitlab,

  // Monitoring
  'prometheus': SiPrometheus,
  'grafana': SiGrafana,

  // Message Queues
  'rabbitmq': SiRabbitmq,

  // API & GraphQL
  'graphql': SiGraphql,
  'rest': HiOutlineServerStack,
  'rest api': HiOutlineServerStack,

  // Third-party services
  'supabase': SiSupabase,
  'openai': SiOpenai,
  'stripe': SiStripe,
  'resend': BiEnvelope,

  // Communication
  'slack': SiSlack,
  'discord': SiDiscord,

  // Design
  'figma': SiFigma,

  // Testing
  'jest': SiJest,

  // Build tools
  'webpack': SiWebpack,

  // Package managers
  'npm': SiNpm,
  'yarn': SiYarn,

  // Version control
  'git': SiGithub,
  'github': SiGithub,
  'gitlab': SiGitlab,

  // OS
  'linux': SiLinux,
  'macos': SiApple,

  // AI/ML
  'ai': SiOpenai,
  'llm': SiOpenai,
  'gpt': SiOpenai,
  'chatgpt': SiOpenai,
  'anthropic': HiOutlineCpuChip,
  'claude': HiOutlineCpuChip,

  // Generic fallbacks
  'api': HiOutlineServerStack,
  'backend': HiOutlineServerStack,
  'server': HiOutlineServerStack,
  'frontend': HiOutlineCube,
  'database': HiOutlineCircleStack,
  'terminal': DiTerminal,
  'cli': DiTerminal,
};

// Get icon for a tech name (case-insensitive)
export const getTechIcon = (tech: string): IconType | null => {
  const normalized = tech.toLowerCase().trim();
  return techIconMap[normalized] || null;
};

// Get multiple icons for a tech stack array
export const getTechIcons = (techStack: string[], maxIcons: number = 3): Array<{ name: string; Icon: IconType }> => {
  const icons: Array<{ name: string; Icon: IconType }> = [];

  for (const tech of techStack) {
    if (icons.length >= maxIcons) break;

    const Icon = getTechIcon(tech);
    if (Icon) {
      icons.push({ name: tech, Icon });
    }
  }

  return icons;
};

// Props for TechStackIcons component
interface TechStackIconsProps {
  techStack: string[];
  maxIcons?: number;
  size?: number;
  className?: string;
  iconClassName?: string;
  showTooltip?: boolean;
}

// Component to display tech stack icons
export const TechStackIcons = ({
  techStack,
  maxIcons = 3,
  size = 16,
  className = '',
  iconClassName = '',
  showTooltip = true,
}: TechStackIconsProps) => {
  const icons = getTechIcons(techStack, maxIcons);

  if (icons.length === 0) {
    return null;
  }

  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      {icons.map(({ name, Icon }, index) => (
        <span
          key={index}
          className={`flex items-center justify-center ${iconClassName}`}
          title={showTooltip ? name : undefined}
        >
          <Icon size={size} />
        </span>
      ))}
    </div>
  );
};

// Props for MainTechIcon component (for the large icon display)
interface MainTechIconProps {
  techStack: string[];
  itemName: string;
  fallbackEmoji?: string;
  size?: number;
  className?: string;
}

// Component to display the main/primary tech icon (largest/most prominent tech)
export const MainTechIcon = ({
  techStack,
  itemName,
  fallbackEmoji,
  size = 24,
  className = '',
}: MainTechIconProps) => {
  // Try to get icon from tech stack
  const icons = getTechIcons(techStack, 1);

  // Try to match by item name as fallback
  if (icons.length === 0) {
    const nameIcon = getTechIcon(itemName);
    if (nameIcon) {
      icons.push({ name: itemName, Icon: nameIcon });
    }
  }

  // If we have an icon, display it
  if (icons.length > 0) {
    const { name, Icon } = icons[0];
    return (
      <span className={`flex items-center justify-center ${className}`} title={name}>
        <Icon size={size} />
      </span>
    );
  }

  // Fallback to emoji if provided
  if (fallbackEmoji) {
    return <span className={`text-xl ${className}`}>{fallbackEmoji}</span>;
  }

  // Ultimate fallback - generic cube icon
  return (
    <span className={`flex items-center justify-center ${className}`}>
      <HiOutlineCube size={size} />
    </span>
  );
};

export default TechStackIcons;
