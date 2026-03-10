/** Application entry point */
import './index.css';
import { initRouter } from './router.js';

const container = document.getElementById('main-content')!;
initRouter(container);
