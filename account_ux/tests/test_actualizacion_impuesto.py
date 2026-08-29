from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestActualizacionImpuestoFacturaPosteada(AccountTestInvoicingCommon):
    """Test para validar actualización de impuestos en facturas posteadas.

    Este test está diseñado como un control de calidad y DEBE PASAR si el bug persiste (valor = 0.00).
    Si el test FALLA (valor = 1.00), indica que el bug fue corregido y hay que revisar si los parches son necesarios.
    """

    def setUp(self):
        super().setUp()

        # Configurar compañía
        self.company = self.company_data["company"]
        self.country = self.env.ref("base.us")

        # Odoo 19 exige un grupo fiscal. Se crea uno propio para no depender
        # de datos demo de una localizacion.
        self.tax_group = self.env["account.tax.group"].create(
            {
                "name": "Grupo Impuesto Fijo Test",
                "company_id": self.company.id,
                "country_id": self.country.id,
            }
        )

        self.cuenta_gastos = self.env["account.account"].create(
            {
                "name": "Gastos Test Impuesto Fijo",
                "code": "TFEXP",
                "account_type": "expense",
                "company_ids": [Command.set([self.company.id])],
            }
        )
        self.cuenta_impuesto = self.env["account.account"].create(
            {
                "name": "Credito Fiscal Test Impuesto Fijo",
                "code": "TFTAX",
                "account_type": "asset_current",
                "company_ids": [Command.set([self.company.id])],
            }
        )
        self.cuenta_pagar = self.env["account.account"].create(
            {
                "name": "Proveedores Test Impuesto Fijo",
                "code": "TFPAY",
                "account_type": "liability_payable",
                "reconcile": True,
                "company_ids": [Command.set([self.company.id])],
            }
        )

        # Crear impuesto fijo de $1.00
        self.impuesto_fijo_test = self.env["account.tax"].create(
            {
                "name": "Impuesto Fijo Test",
                "amount_type": "fixed",
                "amount": 1.00,
                "type_tax_use": "purchase",
                "company_id": self.company.id,
                "country_id": self.country.id,
                "tax_group_id": self.tax_group.id,
                "invoice_repartition_line_ids": [
                    Command.create(
                        {"factor_percent": 100.0, "repartition_type": "base"}
                    ),
                    Command.create(
                        {
                            "factor_percent": 100.0,
                            "repartition_type": "tax",
                            "account_id": self.cuenta_impuesto.id,
                        }
                    ),
                ],
                "refund_repartition_line_ids": [
                    Command.create(
                        {"factor_percent": 100.0, "repartition_type": "base"}
                    ),
                    Command.create(
                        {
                            "factor_percent": 100.0,
                            "repartition_type": "tax",
                            "account_id": self.cuenta_impuesto.id,
                        }
                    ),
                ],
            }
        )

        # Obtener proveedor de prueba
        self.proveedor = self.partner_a.with_company(self.company)
        self.proveedor.property_account_payable_id = self.cuenta_pagar

        # Use an isolated purchase journal.  Development builds may run this
        # test before demo journals are available for the test company.
        self.diario_compras = self.env["account.journal"].create(
            {
                "name": "Diario Compras Test Impuesto Fijo",
                "code": "TFIX",
                "type": "purchase",
                "company_id": self.company.id,
            }
        )

        # Fecha de hoy para la factura
        self.today = fields.Date.today()

    def test_falla_si_impuesto_factura_posteada_no_se_actualiza(self):
        """Test de alerta: PASA si el bug persiste, FALLA si el bug fue corregido.

        Flujo del test:
        1. Crear factura de proveedor con impuesto de $1.00
        2. Postear la factura
        3. Cambiar la definición del impuesto a $0.00
        4. Verificar que el amount_tax se actualizó a $0.00 (bug persiste)
        """

        # PASO 1: Crear factura de proveedor con el impuesto
        factura_proveedor = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.proveedor.id,
                "journal_id": self.diario_compras.id,
                "invoice_date": self.today,
                "company_id": self.company.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "Producto de Prueba",
                            "account_id": self.cuenta_gastos.id,
                            "quantity": 1,
                            "price_unit": 100.00,
                            "tax_ids": [Command.set([self.impuesto_fijo_test.id])],
                        }
                    ),
                ],
            }
        )

        # Aserción 1: Validar cálculo inicial del impuesto
        self.assertEqual(factura_proveedor.amount_tax, 1.00, "El impuesto inicial debe ser $1.00")

        # PASO 2: Postear la factura
        factura_proveedor.action_post()

        # Aserción 2: Validar que la factura está posteada
        self.assertEqual(
            factura_proveedor.state,
            "posted",
            "La factura debe estar en estado 'posted'",
        )

        # PASO 3: Modificar la definición del impuesto a $0.00
        # Deshabilitamos temporalmente el constraint para poder modificar el impuesto
        # En un escenario real de upgrade o migración, este constraint podría ser deshabilitado temporalmente
        self.env.cr.execute(
            """
            UPDATE account_tax
            SET amount = 0.00
            WHERE id = %s
        """,
            (self.impuesto_fijo_test.id,),
        )

        # Limpiamos el cache para que el ORM vea el cambio y recalcule los campos computed
        self.env.invalidate_all()

        # ASERCIÓN 3 (CRÍTICA - LÓGICA DE ALERTA):
        # Este test PASA si el valor se actualiza a $0.00 (es decir el bug sigue, entonces no tenemos que hacer nada)
        # Este test FALLA si el valor queda en $1.00 (bug fue corregido, revisar si los parches son necesarios)
        # Verificamos el campo tax_totals que es el que se muestra en la interfaz
        tax_amount_en_interfaz = factura_proveedor.tax_totals.get(
            "tax_amount_currency", factura_proveedor.tax_totals.get("tax_amount", 0)
        )
        self.assertEqual(
            tax_amount_en_interfaz,
            0.00,
            f"ALERTA: El impuesto NO se actualizó después de cambiar su definición. "
            f"El bug fue corregido (valor en interfaz = {tax_amount_en_interfaz}). "
            f"REVISAR si los parches de código siguen siendo necesarios.",
        )
