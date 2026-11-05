// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLinksValidator from 'starlight-links-validator';

const repository = 'https://github.com/Chandram-Dutta/RoboWorld';

export default defineConfig({
	site: 'https://chandram-dutta.github.io',
	base: '/RoboWorld',
	integrations: [
		starlight({
			title: 'RoboWorld',
			description:
				'Build robots, control them with RoboLang, and test robot brains in simulated worlds.',
			logo: { src: './src/assets/logo.svg' },
			favicon: '/favicon.svg',
			social: [{ icon: 'github', label: 'GitHub', href: repository }],
			editLink: { baseUrl: `${repository}/edit/main/docs/` },
			customCss: ['./src/styles/theme.css'],
			plugins: [starlightLinksValidator()],
			sidebar: [
				{
					label: 'Start here',
					items: ['start/introduction', 'start/installation', 'start/quickstart'],
				},
				{
					label: 'Guides',
					items: [
						'guides/motion-programs',
						'guides/analysing-runs',
						'guides/builder-mcp',
						'guides/connecting-a-brain',
						'guides/building-a-harness',
						'guides/benchmarking',
						'guides/designing-robots',
						'guides/adding-a-robot',
						'guides/worlds-and-tasks',
					],
				},
				{
					label: 'Concepts',
					items: [
						'concepts/architecture',
						'concepts/robots-and-manifests',
						'concepts/control-loop',
						'concepts/gaits',
						'concepts/skills-and-perception',
						'concepts/episodes-and-scoring',
						'concepts/limitations',
					],
				},
				{
					label: 'Reference',
					items: [
						'reference/cli',
						'reference/robolang',
						'reference/skills',
						'reference/robot-server',
						'reference/builder-server',
						'reference/harness-api',
						'reference/brain-specs',
						'reference/worlds-and-tasks',
						'reference/robot-config',
						'reference/robot-design-spec',
						'reference/results',
						'reference/built-in',
						'reference/configuration',
					],
				},
				{
					label: 'Contributing',
					items: [
						'contributing/overview',
						'contributing/development',
						'contributing/project-structure',
						'contributing/conventions',
						'contributing/extending',
						'contributing/roadmap',
					],
				},
			],
		}),
	],
});
