from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Check that your Gemini key and model work.  '
            'Usage: python manage.py check_gemini   |   --models   |   --model <name>')

    def add_arguments(self, parser):
        parser.add_argument('--models', action='store_true',
                            help='List the model names your key is allowed to use')
        parser.add_argument('--model', default='',
                            help='Test this model instead of GEMINI_MODEL (e.g. your backup model)')

    def handle(self, *args, **options):
        if not settings.GEMINI_API_KEY:
            raise CommandError('GEMINI_API_KEY is empty. Put it in your .env file (see the setup steps).')

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY,
                              http_options=types.HttpOptions(timeout=60000))

        if options['models']:
            try:
                names = sorted(m.name.replace('models/', '') for m in client.models.list()
                               if 'generateContent' in (m.supported_actions or []))
            except Exception as error:
                raise CommandError(f'Could not list the models: {error}')
            self.stdout.write('Models your key can use (copy one into GEMINI_MODEL in .env):')
            for name in names:
                self.stdout.write(f'  {name}')
            return

        model = options['model'] or settings.GEMINI_MODEL
        try:
            response = client.models.generate_content(
                model=model, contents='Reply with the single word: ready')
        except Exception as error:
            raise CommandError(f'Gemini call failed with model "{model}": {error}')

        self.stdout.write(self.style.SUCCESS(
            f'Gemini works. Model "{model}" replied: {(response.text or "").strip()}'))